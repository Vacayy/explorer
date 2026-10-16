"""개인 투자 열기 수집 (D-231, docs/specs/retail-heat.md) — launchd `retail` 평일 18:30.

금융투자협회 통계(신용융자·예탁금·반대매매·시장 거래대금/시총, 키 불필요) + 한국거래소(개인 매수·매도, ETF —
.env KRX_ID·KRX_PW 있을 때만). 첫 실행은 1999년부터, 이후 최근 30일. 구간 스냅샷 갱신. 모델 호출 0.

  python scripts/collect_retail.py            # 증분
  python scripts/collect_retail.py --full     # 전체 다시
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db  # noqa: E402
from pipeline import retail_heat as rh  # noqa: E402
from pipeline.ops import run_job  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    init_db()

    def job():
        conn = get_connection()
        try:
            r = rh.collect(conn, full=args.full)
        finally:
            conn.close()
        print(f"[retail] {r}")
        if r.get("krx_error"):   # 협회 데이터는 저장됐지만 개인 거래가 비었다 — 조용히 넘어가지 않고 job_runs에 오류로
            raise RuntimeError(f"협회 {r['kofia_rows']}행 저장, 한국거래소 실패: {r['krx_error']}")
        return r
    run_job("retail", job)


if __name__ == "__main__":
    main()
