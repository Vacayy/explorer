"""companies의 market/sector를 FinanceDataReader(KRX-DESC)로 채운다.

pykrx 섹터 엔드포인트는 KRX 로그인이 필요해져 FDR을 사용.
실행 후 seed_entities.py를 다시 돌리면 sector 노드 + MEMBER_OF 엣지가 생성된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from database import get_connection, init_db


def seed_sectors():
    import FinanceDataReader as fdr

    init_db()
    print("Fetching KRX-DESC listing from FinanceDataReader...")
    df = fdr.StockListing("KRX-DESC")
    print(f"Got {len(df)} listings")

    def _clean(v):
        if v is None or isinstance(v, float):  # None 또는 NaN
            return None
        s = str(v).strip()
        return s or None

    conn = get_connection()
    updated = 0
    for _, row in df.iterrows():
        code = str(row["Code"]).zfill(6)
        # 주의: KRX-DESC의 'Sector'는 코스닥 소속부(중견기업부 등)이고,
        # 'Industry'가 KSIC 업종명(반도체 제조업 등)이다. Industry를 사용한다.
        sector = _clean(row.get("Industry"))
        market = _clean(row.get("Market"))
        cur = conn.execute(
            "UPDATE companies SET sector=COALESCE(?, sector), market=COALESCE(?, market) "
            "WHERE stock_code=?",
            (sector, market, code),
        )
        updated += cur.rowcount
    conn.commit()

    n_sector = conn.execute(
        "SELECT count(*) FROM companies WHERE sector IS NOT NULL AND sector != ''"
    ).fetchone()[0]
    conn.close()
    print(f"updated rows: {updated}, companies with sector: {n_sector}")


if __name__ == "__main__":
    seed_sectors()
