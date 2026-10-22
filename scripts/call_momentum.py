"""실적 발언 모멘텀 (D-217, docs/specs/transcript-momentum.md) — launchd dev.explorer.callmomentum / callmomentumweekly.

  python scripts/call_momentum.py --daily     # 나스닥100 동기화(월 1회) → SEC 8-K → AV 컨콜 → 추출(최대 60건) → 판정 → 후보 AI 요약
  python scripts/call_momentum.py --fresh     # 낮 회차: 이번 시즌 발표 중 아침에 없던 녹취록만(Fool) → 정리 → 그 회사만 추출 → 판정 → 후보 AI 요약
  python scripts/call_momentum.py --weekly    # 지난 7일 새 모멘텀 텔레그램
  python scripts/call_momentum.py --weekly --dry-run
단계별 결과·실패는 job_runs(cm_*)에 남긴다. SEC 연락처(.env SEC_USER_AGENT)가 없으면 그 단계만 error로 남기고 나머지는 돈다.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.ops import record_run


def step(name, fn):
    started = time.time()
    try:
        r = fn()
        record_run(name, "ok", str(r)[:500], int((time.time() - started) * 1000))
        print(f"[{name}]", r)
        return r
    except Exception as e:  # noqa: BLE001 — 다음 단계는 계속 돌리고 실패는 남긴다
        record_run(name, "error", f"{type(e).__name__}: {str(e)[:300]}", int((time.time() - started) * 1000))
        print(f"[{name}] 실패: {type(e).__name__}: {e}")
        return None


def ndx_due(conn) -> bool:
    r = conn.execute("SELECT max(ran_at) FROM job_runs WHERE job='cm_ndx_sync' AND status='ok'").fetchone()[0]
    return not r or conn.execute("SELECT julianday('now') - julianday(?) > 30", (r,)).fetchone()[0]


def daily(extract_limit: int):
    from pipeline import call_momentum as cm, sec_filings as sec, transcript as tr
    conn = get_connection()
    try:
        if ndx_due(conn):
            step("cm_ndx_sync", tr.sync_nasdaq100)
        follows = [dict(r) for r in conn.execute("SELECT ticker, company_name, entity_id FROM transcript_follow WHERE active=1")]
        step("cm_sec", lambda: sec.collect(conn, follows))
        step("cm_av", lambda: tr.collect_and_process(budget=22))
        step("cm_extract", lambda: cm.extract_pending(conn, limit=extract_limit))
        step("cm_judge", lambda: cm.judge(conn))
        step("cm_summary", lambda: cm.summarize(conn))
    finally:
        conn.close()


def fresh():
    from pipeline import call_momentum as cm, transcript as tr
    conn = get_connection()
    try:
        r = step("cm_fresh", tr.collect_fresh)
        if r and r["tickers"]:
            step("cm_extract", lambda: cm.extract_pending(conn, limit=20, only=r["tickers"]))
            step("cm_judge", lambda: cm.judge(conn, r["tickers"]))
            step("cm_summary", lambda: cm.summarize(conn))
    finally:
        conn.close()


def weekly(dry_run: bool):
    from pipeline import call_momentum as cm, portfolio_alerts as pa
    from pipeline.notify import send_telegram
    conn = get_connection()
    try:
        conn.executescript(pa.SCHEMA)
        items, header = cm.weekly_message(conn)
        send = (lambda t: print(t) or True) if dry_run else send_telegram
        n = pa._send(conn, items, header, send, dry_run)
        if not dry_run:
            record_run("cm_weekly", "ok", f"sent {n}", None)
        print("[cm_weekly]", n)
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--daily", action="store_true")
    mode.add_argument("--weekly", action="store_true")
    mode.add_argument("--fresh", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--extract-limit", type=int, default=60)
    args = ap.parse_args()
    init_db()
    if args.daily:
        daily(args.extract_limit)
    elif args.fresh:
        fresh()
    else:
        weekly(args.dry_run)
