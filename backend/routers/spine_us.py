"""미국 종목 도시에 API (docs/specs/us-dossier.md) — 경량 헤더 취합.

헤더(yfinance 시세·밸류) + 해소된 entity + 최근 컨콜 메타만. 렌즈는 기존 `/stock/{ticker}/lens?market=us`,
컨콜 상세·내러티브·피드는 각 전용 엔드포인트를 FE가 entity_id/ticker로 재사용.
"""
from fastapi import APIRouter, HTTPException

from database import get_connection
from models.us import UsDossier

router = APIRouter(prefix="/api/spine/us", tags=["spine"])


@router.get("/{ticker}", response_model=UsDossier)
def us_dossier(ticker: str):
    from pipeline.us_data import get_fundamentals, resolve_us
    conn = get_connection()
    eid, name = resolve_us(conn, ticker)
    tr = conn.execute("""
        SELECT id, fiscal_year, fiscal_period, call_date FROM transcripts
        WHERE ticker=? ORDER BY call_date DESC LIMIT 1""", (ticker.upper(),)).fetchone()
    conn.close()
    fund = get_fundamentals(ticker)
    if not fund and eid is None:
        raise HTTPException(404, "US 종목 데이터를 찾을 수 없습니다")
    return UsDossier(ticker=ticker.upper(), name=name or ticker.upper(), entity_id=eid,
                     fundamentals=fund, latest_transcript=dict(tr) if tr else None)
