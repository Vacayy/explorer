"""Market Today 화두 → 내러티브 연결 백필·재계산 (ia-redesign §9) — 결정적, LLM 0.

새 회차는 생성 직후 자동으로 연결된다(pipeline/market_today.run). 이 스크립트는 연결 표가 생기기 전 회차를
한 번 채우거나, 규칙을 바꾼 뒤 다시 계산할 때 쓴다. 끝에 내러티브 후보도 다시 계산한다.

  python scripts/link_market_today.py                 # 연결 안 된 회차만
  python scripts/link_market_today.py --all           # 전부 다시
  python scripts/link_market_today.py --since 2026-11-03
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="이미 연결한 회차도 다시")
    ap.add_argument("--since", default=None, help="이 거래일(포함)부터")
    a = ap.parse_args()
    init_db()
    from pipeline.market_today_links import link_since, refresh_candidates
    conn = get_connection()
    try:
        r = link_since(conn, a.since, only_missing=not a.all)
        r["candidates"] = refresh_candidates(conn)
        conn.commit()
        topics = conn.execute("SELECT COUNT(*) FROM market_today m, json_each(m.items_json)").fetchone()[0]
        linked = conn.execute("SELECT COUNT(DISTINCT mt_id || ':' || item_idx) FROM market_today_links").fetchone()[0]
        print(f"회차 {r['sessions']} · 연결 {r['links']} · 연결된 화두 {linked}/{topics} · 후보 {r['candidates']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
