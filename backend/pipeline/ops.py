"""운영 관리 — cron 작업 on/off 플래그 + 실행 로그 (관리자 페이지, D-055).

자동화가 늘수록 비용·가시성 통제가 필요 — 관리자가 작업을 끄고, 최근 실행/변경을 본다.
게이트: 각 생성 스크립트 main을 run_job(name, fn)으로 감싸 ①플래그 off면 skip ②실행 기록.
"""
import json
import time

from database import get_connection

# 관리 대상 작업 레지스트리 (name, 라벨, 설명, 진입점) — 생성/비용 큰 것 위주.
# 진입점 = 실제로 실행되는 스크립트/함수 (관리자 페이지에서 무엇이 도는지 가시화).
JOBS: list[tuple[str, str, str, str]] = [
    ("compute_narratives", "내러티브 생성", "opus — 주제별 서사·인과 그래프 물질화", "scripts/compute_narratives.py"),
    ("compute_digests", "다이제스트", "haiku — 종목 1D/7D 요약", "scripts/compute_digests.py"),
    ("scan_actions", "기업활동 스캔", "haiku — DART 공시 스캔·요약", "scripts/scan_actions.py"),
    ("agent_proposals", "에이전트 제안", "제안 스캔 — 소외·상충·리포트 제안·반증 감시", "scripts/scan_agent_proposals.py"),
    ("vocab_merge", "노드 통합", "온톨로지 유사 노드 교통정리 — sonnet 병합 판정→승인 큐(D-050)", "scan_agent_proposals.py → scan_vocab_merges"),
    ("promote_knowledge", "지식 승격", "주 1회 — 반복 관측 검증 지식 승격", "scripts/promote_knowledge.py"),
    ("collect_transcripts", "컨콜 수집", "Alpha Vantage — 팔로우 미국 기업 실적 컨콜 → raw_documents(온톨로지 편입)", "scripts/collect_transcripts.py"),
    ("collect_trade", "수출입 수집", "관세청 — 팔로우 품목 월별 수출입 통계 + 관련 종목(파급 논리) 부트스트랩", "scripts/collect_trade.py"),
    ("refresh_questions", "질문 트래커 갱신", "일 1회 — 자동도출(지배 내러티브) + 프록시 관측 갱신(numeric/sentiment) + 재판정", "scripts/refresh_questions.py"),
]
JOB_LABEL = {n: (label, desc) for n, label, desc, _ep in JOBS}


def flag_enabled(name: str, default: bool = True) -> bool:
    conn = get_connection()
    row = conn.execute("SELECT enabled FROM feature_flags WHERE name=?", (name,)).fetchone()
    conn.close()
    return bool(row["enabled"]) if row else default


def set_flag(name: str, enabled: bool) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO feature_flags (name, enabled, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at",
        (name, 1 if enabled else 0))
    conn.commit()
    conn.close()


def list_flags() -> dict[str, bool]:
    conn = get_connection()
    rows = conn.execute("SELECT name, enabled FROM feature_flags").fetchall()
    conn.close()
    return {r["name"]: bool(r["enabled"]) for r in rows}


def record_run(job: str, status: str, summary: str = "", duration_ms: int | None = None) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO job_runs (job, status, summary, duration_ms, ran_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))", (job, status, summary[:500], duration_ms))
    conn.commit()
    conn.close()


def recent_runs(limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT job, status, summary, duration_ms, ran_at FROM job_runs ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _summarize(r) -> str:
    if isinstance(r, dict):
        return " · ".join(f"{k} {v}" for k, v in r.items() if isinstance(v, (int, str)))[:300]
    return str(r)[:300] if r is not None else ""


def run_job(name: str, fn):
    """생성 스크립트 게이트 — 플래그 off면 skip+기록, on이면 실행+기록(요약·소요시간·에러)."""
    if not flag_enabled(name):
        record_run(name, "skipped", "비활성(관리자 off)")
        print(f"[{name}] skipped — flag off")
        return None
    t0 = time.time()
    try:
        r = fn()
        record_run(name, "ok", _summarize(r), int((time.time() - t0) * 1000))
        return r
    except Exception as e:  # noqa: BLE001 — 기록 후 재전파
        record_run(name, "error", f"{type(e).__name__}: {str(e)[:200]}", int((time.time() - t0) * 1000))
        raise


# ── LLM 엔진 생사 감시 (D-106) ─────────────────────────────────────────────
# 배경: cron이 GUI 세션 밖이라 키체인(claude 자격증명)에 접근하지 못해 모든 LLM 호출이
# `Not logged in`으로 죽었는데(45,294건, 7/17~8/18) 한 달간 아무도 몰랐다. 각 파이프라인이
# 조용히 fallback(enrich→키워드, digest→raw)해 표면적으로는 돌아가는 것처럼 보였기 때문.
# → 값싼 프로브 1콜로 엔진 생사를 명시 신호로 만들고, 죽어 있으면 홈·텔레그램 최상단에 띄운다.
LLM_PROBE = "llm_probe"


def probe_llm() -> dict:
    """LLM 엔진에 haiku 1콜을 던져 생사 확인 → job_runs 기록.

    비용 가드: 오늘 이미 ok면 재프로브하지 않는다(하루 1콜). 단 마지막이 error면
    매 회차 재시도해 복구를 즉시 감지한다 — 고장 중에만 자주 두드리는 비대칭.
    """
    import subprocess
    from pipeline.enrich import _claude_bin, llm_engine

    conn = get_connection()
    last = conn.execute(
        "SELECT status, date(ran_at, '+9 hours') d FROM job_runs WHERE job=? "
        "ORDER BY id DESC LIMIT 1", (LLM_PROBE,)).fetchone()
    conn.close()
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    if last and last["status"] == "ok" and last["d"] == today:
        return {"status": "ok", "cached": True}

    engine = llm_engine()
    if engine is None:
        record_run(LLM_PROBE, "error", "엔진 미설정 (ENRICH_ENGINE·ANTHROPIC_API_KEY 없음)")
        return {"status": "error", "reason": "엔진 미설정"}
    if engine != "claude-code":
        record_run(LLM_PROBE, "ok", f"engine={engine} (프로브 생략)")
        return {"status": "ok", "engine": engine}

    t0 = time.time()
    try:
        proc = subprocess.run([_claude_bin(), "-p", "--model", "haiku", "ping"],
                              capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        ms = int((time.time() - t0) * 1000)
        if proc.returncode == 0 and proc.stdout.strip():
            record_run(LLM_PROBE, "ok", f"engine=claude-code {ms}ms", ms)
            return {"status": "ok", "engine": "claude-code", "ms": ms}
        # claude는 오류(미로그인·한도)를 stdout에 쓴다 — stderr만 보면 원인이 안 보인다
        reason = (proc.stdout.strip() or proc.stderr.strip())[:200]
        record_run(LLM_PROBE, "error", f"rc={proc.returncode} {reason}", ms)
        return {"status": "error", "reason": reason}
    except Exception as e:  # noqa: BLE001
        ms = int((time.time() - t0) * 1000)
        record_run(LLM_PROBE, "error", f"{type(e).__name__}: {str(e)[:150]}", ms)
        return {"status": "error", "reason": type(e).__name__}


def llm_down_reason() -> str | None:
    """마지막 프로브가 실패면 그 사유, 정상이면 None (홈 브리핑 경고용)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT status, summary FROM job_runs WHERE job=? ORDER BY id DESC LIMIT 1",
        (LLM_PROBE,)).fetchone()
    conn.close()
    if row and row["status"] == "error":
        return (row["summary"] or "원인 불명")[:120]
    return None
