"""수혜 섹터/테마 → 종목 후보 스크린 (action_thesis Phase 1, 결정적·LLM 0).

수혜 섹터(엔티티 이름)와 최근 문서에서 함께 링크된 company 종목을 entity_links
공동언급으로 찾아 RS·밸류·시총·52주 위치로 enrich. MEMBER_OF(KSIC 산업분류)와
theme_surge(투자언어 테마)는 taxonomy가 달라 직접 매칭 불가 → 문서 공동언급이
의미적으로 올바른 연결 (research_candidates 스크린 패턴 재사용, D-023 수혜 종착=섹터).
"""
from datetime import date, timedelta

from pipeline.research_candidates import MAX_DOC_STOCKS, _rs_short
from pipeline.sector_rs import _snapshot

WINDOW_52W = 250      # 52주 위치 창(거래일)
MIN_CO_BENEFIT = 2    # 최소 공동언급 문서 수 (Phase 1.5 — 1회성 우연 제외)
REL_MIN = 0.3         # 관련도 하한 = 이 테마와 함께한 언급 / 전체 언급. 편재 대형주 배제(D-035)


def screen_beneficiaries(conn, sector_name: str, limit: int = 12, days: int = 21) -> list[dict]:
    """섹터명 → 공동언급 종목 후보 + RS·밸류·시총·52주 위치. RS(now) 내림차순 Top N.
    정밀도(Phase 1.5): 공동언급 2+ & 관련도(co/전체언급) 하한 — '모든 시황에 나오는 대형주'가
    아니라 '이 테마에 집중적으로 엮인' 종목만 남긴다."""
    latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    if not latest:
        return []
    d = date.fromisoformat(latest)

    # 섹터→종목: sector_name과 최근 days일 문서에서 함께 링크된 company 종목.
    # 문서당 stock 링크 수가 MAX_DOC_STOCKS 초과인 문서(시황 요약)는 공동언급서 제외.
    linked = conn.execute(f"""
        SELECT c.aliases code, c.id entity_id, c.name, COUNT(DISTINCT tl.doc_id) co
        FROM entity_links tl
        JOIN entities e ON e.id=tl.entity_id AND e.name=?
        JOIN raw_documents rd ON rd.id=tl.doc_id
        JOIN entity_links sl ON sl.doc_id=tl.doc_id AND sl.link_type='stock'
        JOIN entities c ON c.id=sl.entity_id AND c.type='company' AND c.aliases IS NOT NULL
        WHERE tl.link_type IN ('industry','topic')
          AND rd.published_at >= datetime('now', ?)
          AND (SELECT COUNT(*) FROM entity_links x
               WHERE x.doc_id=tl.doc_id AND x.link_type='stock') <= {MAX_DOC_STOCKS}
        GROUP BY c.id""", (sector_name, f"-{days} days")).fetchall()

    raw = {r["code"]: {"entity_id": r["entity_id"], "name": r["name"], "co": r["co"]}
           for r in linked if r["co"] >= MIN_CO_BENEFIT}
    if not raw:
        return []

    # 관련도: 각 후보의 '전체' 종목 언급 수(같은 문서 유니버스 = 비-시황 문서, 창 내). rel=co/total.
    # 편재 대형주(모든 시황에 등장)는 total이 커 rel이 낮아 걸러진다.
    ph_raw = ",".join("?" * len(raw))
    totals = {r["code"]: r["total"] for r in conn.execute(f"""
        SELECT c.aliases code, COUNT(DISTINCT sl.doc_id) total
        FROM entity_links sl
        JOIN entities c ON c.id=sl.entity_id AND c.type='company'
        JOIN raw_documents rd ON rd.id=sl.doc_id
        WHERE sl.link_type='stock' AND c.aliases IN ({ph_raw})
          AND rd.published_at >= datetime('now', ?)
          AND (SELECT COUNT(*) FROM entity_links x
               WHERE x.doc_id=sl.doc_id AND x.link_type='stock') <= {MAX_DOC_STOCKS}
        GROUP BY c.id""", (*raw, f"-{days} days"))}

    cands = {}
    for code, b in raw.items():
        total = totals.get(code, b["co"]) or b["co"]
        rel = b["co"] / total
        if rel >= REL_MIN:
            cands[code] = {**b, "rel": rel}
    if not cands:
        return []
    codes = list(cands)

    rs_now = _rs_short(conn, latest)
    rs_prev = _rs_short(conn, (d - timedelta(days=7)).isoformat())
    snap = _snapshot(conn, latest)

    ph = ",".join("?" * len(codes))
    val = {r["stock_code"]: (r["per"], r["pbr"]) for r in conn.execute(f"""
        SELECT f.stock_code, f.per, f.pbr FROM fundamentals f
        JOIN (SELECT stock_code, max(trade_date) d FROM fundamentals
              WHERE stock_code IN ({ph}) GROUP BY stock_code) t
          ON t.stock_code=f.stock_code AND t.d=f.trade_date""", codes)}

    # 52주 위치: 최근 250거래일 종가 [min,max] 범위 안 현재가 백분위(0~100).
    rng = {r["stock_code"]: (r["mn"], r["mx"]) for r in conn.execute(f"""
        SELECT stock_code, MIN(close) mn, MAX(close) mx FROM (
          SELECT stock_code, close,
                 ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY trade_date DESC) rn
          FROM stock_prices WHERE stock_code IN ({ph}) AND close IS NOT NULL)
        WHERE rn <= {WINDOW_52W} GROUP BY stock_code""", codes)}

    out = []
    for code, b in cands.items():
        now = rs_now.get(code)
        if now is None:   # RS 없으면 추세 렌즈로 랭킹 불가 → 제외
            continue
        close, mcap = snap.get(code, (None, 0))
        per, pbr = val.get(code, (None, None))
        mn, mx = rng.get(code, (None, None))
        pos = None
        if close is not None and mn is not None and mx is not None and mx > mn:
            pos = round((close - mn) / (mx - mn) * 100)
        out.append({
            "stock_code": code, "entity_id": b["entity_id"], "name": b["name"],
            "rs_short": int(now), "rs_prev": int(rs_prev[code]) if code in rs_prev else None,
            "per": round(per, 1) if per is not None else None,
            "pbr": round(pbr, 2) if pbr is not None else None,
            "market_cap": int(mcap) if mcap else None,
            "pos_52w": pos, "co_mentions": int(b["co"]),
            "relevance": round(b["rel"], 2),
        })
    out.sort(key=lambda x: -x["rs_short"])
    return out[:limit]


def graph_activity(conn, days: int = 7, limit: int = 12) -> list[dict]:
    """최근 새 엣지가 붙은 인과 노드(그래프 델타) + 섹터/테마면 수혜 종목 top3 (action_thesis, D-035).
    신호 탭 델타 표면 — '무엇이 그래프에서 새로 뜨거나 갱신됐나'. 활동(new_edges) 내림차순."""
    rows = conn.execute(f"""
        SELECT e.id, e.name, e.type,
               MAX(e.created_at >= datetime('now','-{days} days')) is_new,
               COUNT(*) new_edges
        FROM entity_relations er
        JOIN entities e ON e.id IN (er.src_id, er.dst_id)
        WHERE er.created_at >= datetime('now','-{days} days')
          AND e.type IN ('theme','sector','macro','policy','event')
        GROUP BY e.id
        ORDER BY new_edges DESC, is_new DESC
        LIMIT ?""", (limit,)).fetchall()
    out = []
    for r in rows:
        item = {"id": r["id"], "name": r["name"], "type": r["type"],
                "is_new": bool(r["is_new"]), "new_edges": r["new_edges"], "beneficiaries": []}
        if r["type"] in ("sector", "theme"):
            item["beneficiaries"] = [
                {"stock_code": b["stock_code"], "name": b["name"], "rs_short": b["rs_short"]}
                for b in screen_beneficiaries(conn, r["name"], limit=3)]
        out.append(item)
    return out
