"""미국 종목 도시에 API (docs/specs/us-dossier.md) — 경량 헤더 취합.

헤더(yfinance 시세·밸류) + 해소된 entity + 최근 컨콜 메타만. 렌즈는 기존 `/stock/{ticker}/lens?market=us`,
컨콜 상세·내러티브·피드는 각 전용 엔드포인트를 FE가 entity_id/ticker로 재사용.
"""
from fastapi import APIRouter, HTTPException

import json

from database import get_connection
from models.us import (UsDossier, UsEdge, UsGroup, UsList, UsListItem, UsMention,
                        UsNarrativeRef, UsWorldModel)

router = APIRouter(prefix="/api/spine/us", tags=["spine"])


@router.get("", response_model=UsList)
def us_list():
    """미국 종목 디렉토리 — transcript_follow(=US 유니버스) 그룹별 + 캐시된 렌즈 stance. LLM 0."""
    from pipeline.investor_lens import compute_quadrant
    conn = get_connection()
    rows = conn.execute("""
        SELECT ticker, company_name, group_label FROM transcript_follow
        WHERE active=1 ORDER BY COALESCE(group_label, 'zzz'), ticker""").fetchall()

    def _stance(ticker: str, lt: str):
        s = conn.execute(
            "SELECT stance FROM lens_readings WHERE stock_code=? AND lens_type=? AND market='us' "
            "ORDER BY id DESC LIMIT 1", (ticker, lt)).fetchone()
        return s["stance"] if s else None

    grouped: dict[str, list] = {}
    for r in rows:
        t = r["ticker"]
        vs, ts = _stance(t, "value"), _stance(t, "trend")
        fr = conn.execute("SELECT data_json FROM us_fundamentals WHERE ticker=?", (t,)).fetchone()
        price = None
        if fr:
            try:
                price = json.loads(fr["data_json"]).get("price")
            except Exception:
                price = None
        q = compute_quadrant(vs, ts)
        grouped.setdefault(r["group_label"] or "기타", []).append(UsListItem(
            ticker=t, name=r["company_name"], group_label=r["group_label"],
            value_stance=vs, trend_stance=ts, quadrant_cell=q["cell"] if q else None, price=price))
    conn.close()
    return UsList(groups=[UsGroup(label=g, items=items) for g, items in grouped.items()])


@router.get("/{ticker}/mentions", response_model=list[UsMention])
def us_mentions(ticker: str, limit: int = 20):
    """이 미국 기업 언급 문서(여론) — entity_links 경유. 컨콜·유튜브·인물·뉴스 등 소스 혼합."""
    from pipeline.us_data import resolve_us
    conn = get_connection()
    eid, _ = resolve_us(conn, ticker)
    if eid is None:
        conn.close()
        return []
    rows = conn.execute("""
        SELECT rd.id, rd.source_type, rd.title, rd.url, rd.published_at,
               substr(rd.markdown, 1, 200) excerpt
        FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
        WHERE el.entity_id=? GROUP BY rd.id
        ORDER BY rd.published_at DESC LIMIT ?""", (eid, limit)).fetchall()
    conn.close()
    return [UsMention(id=r["id"], source_type=r["source_type"], title=r["title"], url=r["url"],
                      published_at=r["published_at"], excerpt=r["excerpt"]) for r in rows]


@router.get("/{ticker}/worldmodel", response_model=UsWorldModel)
def us_worldmodel(ticker: str):
    """이 미국 기업 노드의 온톨로지 위치 — 인과 엣지(양방향) + 걸린 내러티브. LLM 0.

    온톨로지 그래프 딥링크는 FE가 entity_id로 `/knowledge/ontology?focus=` 구성.
    """
    from pipeline.us_data import resolve_us
    conn = get_connection()
    eid, _ = resolve_us(conn, ticker)
    if eid is None:
        conn.close()
        return UsWorldModel(entity_id=None, edges=[], narratives=[])
    rows = conn.execute("""
        SELECT r.rel_type, r.effect_direction, r.confidence, r.mechanism, r.narrative_id,
               s.name src, d.name dst, r.src_id
        FROM entity_relations r
        JOIN entities s ON s.id = r.src_id
        JOIN entities d ON d.id = r.dst_id
        WHERE r.epistemic_type='hypothesis' AND r.rel_type IN ('CAUSES','BENEFITS_FROM')
          AND (r.src_id=? OR r.dst_id=?)
        ORDER BY r.confidence DESC LIMIT 12""", (eid, eid)).fetchall()
    edges = [UsEdge(src=r["src"], dst=r["dst"], rel_type=r["rel_type"], direction=r["effect_direction"],
                    confidence=r["confidence"], mechanism=r["mechanism"], self_is_src=(r["src_id"] == eid))
             for r in rows]
    nids = [n for n in {r["narrative_id"] for r in rows} if n]
    narratives = []
    if nids:
        ph = ",".join("?" * len(nids))
        nr = conn.execute(
            f"SELECT topic, max(id) id, title FROM narratives WHERE id IN ({ph}) GROUP BY topic",
            nids).fetchall()
        narratives = [UsNarrativeRef(id=r["id"], topic=r["topic"], title=r["title"]) for r in nr]
    conn.close()
    return UsWorldModel(entity_id=eid, edges=edges, narratives=narratives)


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
