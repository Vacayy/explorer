from fastapi import APIRouter

from database import get_connection
from services.consensus_service import fetch_consensus

router = APIRouter(prefix="/api/consensus", tags=["consensus"])


@router.get("/{stock_code}")
def get_consensus(stock_code: str):
    return fetch_consensus(stock_code)


@router.get("/{stock_code}/history")
def get_fwd_per_history(stock_code: str):
    """12M Fwd PER 추이 — 스냅샷(fetched_date)마다 '가장 가까운 forward 회계연도'의 fwd_per.
    consensus_estimates(일별 수집)에서 시계열화. 리포트 차트용(D-046 forward PER only)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT fetched_date, fiscal_year, fwd_per FROM consensus_estimates "
        "WHERE stock_code=? AND fwd_per IS NOT NULL ORDER BY fetched_date, fiscal_year",
        (stock_code,)).fetchall()
    conn.close()
    # 날짜별로 forward(회계연도 >= 당해년) 중 가장 가까운 것; 없으면 최대 회계연도
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r["fetched_date"]
        year = int(d[:4]) if d and len(d) >= 4 else 0
        cand = by_date.get(d)
        fy = r["fiscal_year"] or 0
        # forward 우선(fy>=year), 그 안에서 최소 fy; forward 없으면 최대 fy
        if cand is None:
            by_date[d] = {"fiscal_year": fy, "fwd_per": r["fwd_per"]}
        else:
            cur = cand["fiscal_year"]
            better = (fy >= year and (cur < year or fy < cur)) or (cur < year and fy > cur)
            if better:
                by_date[d] = {"fiscal_year": fy, "fwd_per": r["fwd_per"]}
    series = [{"date": d, "fwd_per": v["fwd_per"]} for d, v in sorted(by_date.items())]
    return {"items": series}
