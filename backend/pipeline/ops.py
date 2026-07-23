"""운영 관리 — cron 작업 on/off 플래그 + 실행 로그 (관리자 페이지, D-055).

자동화가 늘수록 비용·가시성 통제가 필요 — 관리자가 작업을 끄고, 최근 실행/변경을 본다.
게이트: 각 생성 스크립트 main을 run_job(name, fn)으로 감싸 ①플래그 off면 skip ②실행 기록.
"""
import json
import time

from database import get_connection

# 관리 대상 작업 레지스트리 (name, 라벨, 설명) — 생성/비용 큰 것 위주.
JOBS: list[tuple[str, str, str]] = [
    ("compute_narratives", "내러티브 생성", "opus — 주제별 서사·인과 그래프 물질화"),
    ("compute_digests", "다이제스트", "haiku — 종목 1D/7D 요약"),
    ("scan_actions", "기업활동 스캔", "haiku — DART 공시 스캔·요약"),
    ("agent_proposals", "에이전트 제안", "제안 스캔 — 소외·상충·리포트 제안·반증 감시"),
    ("vocab_merge", "노드 통합", "온톨로지 유사 노드 교통정리 — sonnet 병합 판정→승인 큐(D-050)"),
    ("promote_knowledge", "지식 승격", "주 1회 — 반복 관측 검증 지식 승격"),
]
JOB_LABEL = {n: (label, desc) for n, label, desc in JOBS}


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
