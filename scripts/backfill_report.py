"""재태깅 백필 결과 보고서 — LLM 0 (D-118).

`run_backfill.sh`가 실행 종료 시 자동 호출한다. 중간에 끊겨도(사용량 소진·수면·재부팅)
그 시점까지의 사실이 파일로 남고 **텔레그램으로 발송**된다 — 야간에 끝나는 작업이라
사람이 깨어 있을 때 폰에서 받는 게 맞다. 토큰 사용량은 claude-code 세션 파일에서
직접 집계 — 추정 아님. `--no-telegram`으로 발송 생략.
"""
import json
import pathlib
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))
from database import get_connection, init_db

PROJECT = pathlib.Path(__file__).resolve().parent.parent
REPORT = PROJECT / "logs" / "backfill_report.md"
# claude-code 세션 디렉터리 — 프로젝트 절대경로의 '/'를 '-'로 치환한 이름 규칙에서 유도.
# (사용자명이 박히므로 하드코딩하지 않는다)
SESS = pathlib.Path.home() / ".claude/projects" / str(PROJECT).replace("/", "-")


def _tokens_since(t0: float) -> dict:
    """창 안에서 배치 재태깅이 쓴 토큰 — 세션 파일 실측(프롬프트 지문으로 식별)."""
    agg = {"calls": 0, "output": 0, "thinking": 0, "cache_creation": 0, "cache_read": 0}
    if not SESS.exists():
        return agg
    for p in SESS.glob("*.jsonl"):
        try:
            if p.stat().st_mtime < t0:
                continue
            lines = p.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        if len(lines) > 40 or "제목:" not in "".join(lines[:6]):
            continue
        agg["calls"] += 1
        for ln in lines:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            m = r.get("message")
            if isinstance(m, dict) and m.get("role") == "assistant":
                u = m.get("usage") or {}
                agg["output"] += u.get("output_tokens") or 0
                agg["thinking"] += (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0
                agg["cache_creation"] += u.get("cache_creation_input_tokens") or 0
                agg["cache_read"] += u.get("cache_read_input_tokens") or 0
    return agg


def main() -> None:
    init_db()
    conn = get_connection()
    try:
        tot = conn.execute("SELECT count(*) c FROM raw_documents").fetchone()["c"]
        llm = conn.execute(
            "SELECT count(*) c FROM enrichments WHERE model<>'keyword'").fetchone()["c"]
        kw = conn.execute(
            "SELECT count(*) c FROM enrichments WHERE model='keyword'").fetchone()["c"]
        # doc_causal 대상 풀 — enrich가 진행되면 함께 늘어난다(직렬 의존)
        pool = conn.execute("""
            SELECT count(*) c FROM enrichments en JOIN raw_documents rd ON rd.id=en.doc_id
            WHERE en.model<>'keyword' AND length(COALESCE(rd.markdown,rd.raw_content,''))>=1200
        """).fetchone()["c"]
        done_causal = conn.execute(
            "SELECT count(*) c FROM enrichments WHERE causal_extracted_at IS NOT NULL").fetchone()["c"]
        runs = [dict(r) for r in conn.execute(
            "SELECT status, summary, duration_ms, datetime(ran_at,'+9 hours') kst "
            "FROM job_runs WHERE job='backfill_enrich' ORDER BY id DESC LIMIT 6")]
    finally:
        conn.close()

    last = runs[0] if runs else None
    dur_h = (last["duration_ms"] or 0) / 3_600_000 if last else 0
    t0 = (datetime.now() - timedelta(hours=max(dur_h, 0.1) + 0.2)).timestamp()
    tk = _tokens_since(t0)

    L = [f"# 재태깅 백필 보고서 — {datetime.now():%Y-%m-%d %H:%M} KST", ""]
    L.append("## 마지막 실행")
    if last:
        L.append(f"- 종료 시각 `{last['kst']}` · 상태 `{last['status']}` · 소요 {dur_h:.2f}시간")
        L.append(f"- 요약: `{last['summary']}`")
    else:
        L.append("- job_runs 기록 없음 (첫 실행 중단 등)")
    L += ["", "## 온톨로지 태깅 현황",
          f"- 전체 문서 **{tot:,}건**",
          f"- LLM 태깅 **{llm:,}건 ({llm/max(tot,1)*100:.1f}%)** · 키워드 폴백 **{kw:,}건**",
          f"- 남은 재태깅 대상: **{kw:,}건** ({-(-kw//10)}콜 ≈ {-(-kw//10)*36/3600:.1f}시간)",
          "", "## 다음 단계(doc_causal)에 미친 영향",
          f"- 인과 추출 대상 풀: **{pool:,}건** (enrich 진행에 따라 증가)",
          f"- 추출 완료 **{done_causal:,}건** → 진척 **{done_causal/max(pool,1)*100:.1f}%**",
          f"- 남은 대상 **{max(pool-done_causal,0):,}건** · `extract_doc_causal` 플래그는 OFF",
          "", "## 이번 창에서 실제로 쓴 토큰 (세션 파일 실측)",
          f"- 배치 콜 **{tk['calls']:,}건**",
          f"- output **{tk['output']:,}** (그중 thinking {tk['thinking']:,} = "
          f"{tk['thinking']/max(tk['output'],1)*100:.1f}%)",
          f"- cache_creation {tk['cache_creation']:,} · cache_read {tk['cache_read']:,}"]
    if tk["calls"]:
        L.append(f"- 콜당 output **{tk['output']//tk['calls']:,}**")
    if len(runs) > 1:
        L += ["", "## 최근 실행 이력"]
        L += [f"- `{r['kst']}` {r['status']} — {r['summary']}" for r in runs]
    L += ["", "## 중단 원인 판별",
          "- 요약의 `stopped` 값: `완주` / `데드라인` / `예산 소진`",
          "- 위 셋이 아니고 job_runs 기록도 없으면 **프로세스가 강제 종료된 것**",
          "  (사용량 소진·수면·재부팅). 남은 물량은 다음 02:00 창에서 이어짐."]

    body = "\n".join(L) + "\n"
    REPORT.write_text(body)
    print(f"[backfill-report] {REPORT}")

    # 텔레그램 발송 — 야간에 끝나므로 사람이 깨어 있을 때 폰에서 받게 한다.
    # 마크다운 → HTML 변환·분할은 D-109 경로 재사용. 토큰 0(발송은 LLM 아님).
    if "--no-telegram" not in sys.argv:
        try:
            from pipeline.notify import send_telegram
            from pipeline.telegram_md import to_html
            sent = send_telegram(to_html(body))
            print(f"[backfill-report] 텔레그램 발송 {'성공' if sent else '실패/미설정'}")
        except Exception as e:  # noqa: BLE001 — 발송 실패가 보고서 파일을 막지 않는다
            print(f"[backfill-report] 텔레그램 발송 예외(무시): {type(e).__name__}")


if __name__ == "__main__":
    main()
