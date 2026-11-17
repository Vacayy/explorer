"""The US briefing's pricing ledger extraction as its own computation (refactor_collect_job._run_pricing).

compute_briefing.py runs pricing_ledger.extract_pending() after the briefing; the candidate runs it here on the
computation path once the briefing is in PG, at most argv[1] pending days, and records the run as 'pricing_ledger'.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
from pipeline.ops import record_run  # noqa: E402
from pipeline.pricing_ledger import extract_pending  # noqa: E402

started = time.monotonic()
results = extract_pending(int(sys.argv[1]) if len(sys.argv) > 1 else None)
for r in results:
    print(f"[pricing] {r['trade_date']} {r['status']} 관측 {r.get('observed')} 새 전제 {r.get('new')} {r.get('error') or ''}")
failed = [r['trade_date'] for r in results if r['status'] == 'error']
record_run('pricing_ledger', 'error' if failed else ('ok' if results else 'skipped'),
           f"{len(results)}일 · 실패 {','.join(failed) or '없음'}", int((time.monotonic() - started) * 1000))
