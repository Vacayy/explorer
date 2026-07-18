"""신호 API — signals 테이블 읽기."""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from database import get_connection
from models.spine import SignalItem, SignalsResponse

router = APIRouter(prefix="/api/spine/signals", tags=["spine"])


def _row_to_item(r) -> SignalItem:
    return SignalItem(
        id=r["id"], signal_type=r["signal_type"], entity_id=r["entity_id"],
        entity_name=r["entity_name"], stock_code=r["stock_code"], date=r["date"],
        payload=json.loads(r["payload_json"] or "{}"),
        interpretation=r["interpretation"],
        interpretation_model=r["interpretation_model"],
    )


@router.get("", response_model=SignalsResponse)
def get_signals(
    type: str | None = Query(None, description="mention_surge 등"),
    days: int = Query(7, ge=1, le=90),
):
    conn = get_connection()
    where, params = ["s.date >= ?"], [(date.today() - timedelta(days=days)).isoformat()]
    if type:
        where.append("s.signal_type = ?")
        params.append(type)
    if type == "theme_surge":
        # 매일 재평가되는 state성 신호 — 같은 테마가 연속으로 화두면 날짜마다 row가 쌓인다.
        # 목록엔 테마당 최신 스냅샷만 (히스토리 자체는 signals에 그대로 축적됨, narrative.py
        # _theme_metrics와 동일 패턴).
        where.append("s.date = (SELECT MAX(s2.date) FROM signals s2 "
                      "WHERE s2.signal_type = s.signal_type AND s2.entity_id = s.entity_id)")

    rows = conn.execute(f"""
        SELECT s.id, s.signal_type, s.entity_id, s.date, s.payload_json,
               s.interpretation, s.interpretation_model,
               e.name AS entity_name, e.aliases AS stock_code
        FROM signals s JOIN entities e ON s.entity_id = e.id
        WHERE {" AND ".join(where)}
        ORDER BY s.date DESC, s.id DESC
    """, params).fetchall()
    conn.close()

    return SignalsResponse(
        items=[_row_to_item(r) for r in rows],
        as_of=datetime.now(timezone.utc).isoformat(),
    )


class MomentumRow(BaseModel):
    rank: int
    entity_id: int
    name: str
    stock_code: str | None
    count_7d: int
    prior_7d: int
    score: float          # count_7d / max(prior,1) — 부상 배율
    daily: list[int]      # 최근 14일 일별 언급 (스파크라인)


class MomentumResponse(BaseModel):
    items: list[MomentumRow]
    as_of: str


@router.get("/momentum", response_model=MomentumResponse)
def mention_momentum(limit: int = Query(12, ge=3, le=30)):
    """언급 모멘텀 랭킹 — 이번 주 부상 중인 종목 (카운트→발굴 확장)."""
    from pipeline.dates import parse_dt  # noqa: F401 (published_at ISO 정규화 전제)
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.id entity_id, e.name, e.aliases stock_code,
               sum(rd.published_at >= datetime('now', '-7 days')) c7,
               sum(rd.published_at < datetime('now', '-7 days')
                   AND rd.published_at >= datetime('now', '-14 days')) p7
        FROM entity_links el
        JOIN entities e ON el.entity_id = e.id
        JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.link_type = 'stock' AND e.type = 'company'
        GROUP BY e.id
        HAVING c7 >= 2
    """).fetchall()
    conn.close()

    scored = sorted(
        ({"entity_id": r["entity_id"], "name": r["name"], "stock_code": r["stock_code"],
          "count_7d": r["c7"] or 0, "prior_7d": r["p7"] or 0,
          "score": round((r["c7"] or 0) / max(r["p7"] or 0, 1), 1)}
         for r in rows),
        key=lambda x: (-x["score"], -x["count_7d"]),
    )[:limit]

    # 스파크라인: 최근 14일 일별 언급 카운트
    conn2 = get_connection()
    for s in scored:
        daily = {r["d"]: r["n"] for r in conn2.execute("""
            SELECT date(published_at) d, count(DISTINCT rd.id) n
            FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
            WHERE el.entity_id=? AND el.link_type='stock'
              AND rd.published_at >= datetime('now', '-14 days')
            GROUP BY date(published_at)""", (s["entity_id"],))}
        days = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
        s["daily"] = [daily.get(d, 0) for d in days]
    conn2.close()

    return MomentumResponse(
        items=[MomentumRow(rank=i + 1, **s) for i, s in enumerate(scored)],
        as_of=datetime.now(timezone.utc).isoformat(),
    )


class BacktestRow(BaseModel):
    date: str
    name: str
    stock_code: str | None
    signal_type: str
    ret_5d: float | None    # 신호일 종가 → 5거래일 후 종가 수익률 (%)


class BacktestResponse(BaseModel):
    items: list[BacktestRow]
    avg_ret: float | None
    hit_rate: float | None   # 양(+) 수익 비율
    n: int
    as_of: str


@router.get("/backtest", response_model=BacktestResponse)
def signals_backtest():
    """신호 성적표 — mention_surge 신호 후 5거래일 수익률 (신호의 자기 검증)."""
    conn = get_connection()
    sigs = conn.execute("""
        SELECT s.date, s.signal_type, e.name, e.aliases stock_code
        FROM signals s JOIN entities e ON s.entity_id = e.id
        WHERE s.signal_type = 'mention_surge' AND e.aliases IS NOT NULL
        ORDER BY s.date
    """).fetchall()

    items, rets = [], []
    for s in sigs:
        prices = conn.execute("""
            SELECT trade_date, close FROM stock_prices
            WHERE stock_code=? AND trade_date >= ? AND close IS NOT NULL
            ORDER BY trade_date LIMIT 6
        """, (s["stock_code"], s["date"])).fetchall()
        ret = None
        if len(prices) >= 6 and prices[0]["close"]:
            ret = round((prices[5]["close"] / prices[0]["close"] - 1) * 100, 2)
            rets.append(ret)
        items.append(BacktestRow(date=s["date"], name=s["name"], stock_code=s["stock_code"],
                                 signal_type=s["signal_type"], ret_5d=ret))
    conn.close()
    return BacktestResponse(
        items=items[::-1][:30],
        avg_ret=round(sum(rets) / len(rets), 2) if rets else None,
        hit_rate=round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1) if rets else None,
        n=len(rets),
        as_of=datetime.now(timezone.utc).isoformat(),
    )
