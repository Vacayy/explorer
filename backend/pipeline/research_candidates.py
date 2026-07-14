"""리서치 후보 — 값싼 SQL로 '파볼 만한' 종목을 제안 (감지 LLM 0), 승인 시에만 심층 리서치.

배경(D-020): 비싼 건 opus 추정치 리서치 하나뿐. RS 계산·시총·테마 화두 감지는 전부
공짜 SQL. 그래서 '항상 전 종목 4분면을 opus로 돌린다' 대신 '값싸게 후보를 골라 제안 →
사용자가 승인한 것만 opus'로 간다 — "노동은 기계가, 판단은 사람이".

감지 = 관심 유입(단기 RS 상위 + 상승 추세) ∩ 규모(시총 임계) ∩ 화두(소속 섹터가
theme_surge). 승인 = stock_brief(opus) 실행 → 추정치 방향 콜(up/down/hold) 기록.
"""
import json
from datetime import date, timedelta

from database import get_connection
from pipeline.sector_rs import _percentile, _snapshot

MIN_MCAP = 500_000_000_000    # 5000억 — 유동성·정보 커버리지 최소선
RS_HIGH = 70                   # 단기 RS 상위 30% (시장 대비 관심 유입)
RS_RISE = 8                    # 1주 전 대비 상승폭(pp) — '점차 높아지는' 추세
SHORT_DAYS = 30                # 단기 RS 기준 창
MIN_CO = 1                     # 화두와 공동언급 최소 문서 수 (시황글 제외 후라 1건도 유의미)
MAX_DOC_STOCKS = 6             # 종목 링크가 이보다 많은 문서(시황 요약)는 공동언급서 제외
LIMIT = 12


def _rs_short(conn, as_of: str) -> dict[str, float]:
    """해당일 기준 종목별 단기 RS = 최근 30일 수익률의 전 종목 백분위(0~100)."""
    cur = _snapshot(conn, as_of)
    base = _snapshot(conn, (date.fromisoformat(as_of) - timedelta(days=SHORT_DAYS)).isoformat())
    rets = {}
    for code, (px, _) in cur.items():
        b = base.get(code)
        if b and b[0] and px:
            rets[code] = (px - b[0]) / b[0] * 100
    return _percentile(rets)


def compute_research_candidates() -> list[dict]:
    """오늘의 리서치 후보 감지 → research_candidates upsert (proposed). LLM 0."""
    conn = get_connection()
    latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    if not latest:
        conn.close()
        return []
    d = date.fromisoformat(latest)
    rs_now = _rs_short(conn, latest)
    rs_prev = _rs_short(conn, (d - timedelta(days=7)).isoformat())
    cur = _snapshot(conn, latest)

    # 화두 테마 — theme_surge 최신 신호 (테마별 점유율 상승폭)
    hot = {r["name"]: json.loads(r["payload_json"]) for r in conn.execute("""
        SELECT e.name, s.payload_json FROM signals s JOIN entities e ON e.id=s.entity_id
        WHERE s.signal_type='theme_surge'
          AND s.date=(SELECT MAX(date) FROM signals WHERE signal_type='theme_surge')""")}
    if not hot:
        conn.close()
        return []

    # 종목 ↔ 화두 연결: '최근 14일 그 화두와 함께 언급된' 종목 (문서 공동 링크).
    # MEMBER_OF(KSIC 산업분류)와 theme_surge(투자언어 테마)는 taxonomy가 달라 직접
    # 매칭 불가 → 문서 공동언급이 의미적으로 올바른 연결 ("이 종목이 그 화두로 회자됨").
    ph = ",".join("?" * len(hot))
    linked = conn.execute(f"""
        SELECT c.aliases code, c.id entity_id, c.name, e.name theme, COUNT(*) co
        FROM entity_links tl
        JOIN entities e ON e.id=tl.entity_id AND e.name IN ({ph})
        JOIN raw_documents rd ON rd.id=tl.doc_id
        JOIN entity_links sl ON sl.doc_id=tl.doc_id AND sl.link_type='stock'
        JOIN entities c ON c.id=sl.entity_id AND c.type='company' AND c.aliases IS NOT NULL
        WHERE tl.link_type IN ('industry','topic')
          AND rd.published_at >= datetime('now','-14 days')
          AND (SELECT COUNT(*) FROM entity_links x
               WHERE x.doc_id=tl.doc_id AND x.link_type='stock') <= {MAX_DOC_STOCKS}
        GROUP BY c.id, e.name""", list(hot)).fetchall()

    # 종목별 가장 강하게 엮인 화두 (공동언급 최다) 하나만
    best: dict[str, dict] = {}
    for r in linked:
        code = r["code"]
        if r["co"] < MIN_CO:
            continue
        if code not in best or r["co"] > best[code]["co"]:
            best[code] = {"entity_id": r["entity_id"], "name": r["name"],
                          "theme": r["theme"], "co": r["co"]}

    cands = []
    for code, b in best.items():
        now, prev = rs_now.get(code), rs_prev.get(code)
        mcap = cur.get(code, (0, 0))[1]
        if now is None or prev is None:
            continue
        if now < RS_HIGH or (now - prev) < RS_RISE or (mcap or 0) < MIN_MCAP:
            continue
        cands.append({
            "stock_code": code, "entity_id": b["entity_id"], "name": b["name"],
            "rs_short": int(now), "rs_short_prev": int(prev), "market_cap": int(mcap),
            "sector": b["theme"], "share_delta_pp": hot[b["theme"]].get("share_delta_pp"),
            "rise": now - prev,
        })
    # RS 상승폭 큰 순 → 상위만 (제안은 소수 정예)
    cands.sort(key=lambda x: -x["rise"])
    cands = cands[:LIMIT]

    for c in cands:
        conn.execute("""
            INSERT INTO research_candidates
              (stock_code, entity_id, name, detected_date, rs_short, rs_short_prev,
               market_cap, sector, share_delta_pp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed')
            ON CONFLICT(stock_code, detected_date) DO UPDATE SET
              rs_short=excluded.rs_short, rs_short_prev=excluded.rs_short_prev,
              market_cap=excluded.market_cap, sector=excluded.sector,
              share_delta_pp=excluded.share_delta_pp
        """, (c["stock_code"], c["entity_id"], c["name"], latest, c["rs_short"],
              c["rs_short_prev"], c["market_cap"], c["sector"], c["share_delta_pp"]))
    conn.commit()
    conn.close()
    return cands


def list_candidates(status: str = "proposed", limit: int = 20) -> list[dict]:
    """제안(또는 완료) 후보 — 최신 감지일 우선, RS 상승폭순."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, stock_code, name, detected_date, rs_short, rs_short_prev,
               market_cap, sector, share_delta_pp, status, revision_call, researched_at
        FROM research_candidates WHERE status=?
        ORDER BY detected_date DESC, (rs_short - rs_short_prev) DESC LIMIT ?
    """, (status, limit)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["revision_call"] = json.loads(r["revision_call"]) if r["revision_call"] else None
        out.append(d)
    return out


def approve_candidate(candidate_id: int) -> dict:
    """승인 → stock_brief(opus) 실행, 추정치 방향 콜 기록. 멱등(브리프 hash 가드 재사용)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT stock_code, status FROM research_candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        conn.close()
        return {"status": "not_found"}
    stock_code = row["stock_code"]
    conn.close()

    from pipeline.stock_brief import compute_brief
    result = compute_brief(stock_code)   # opus (또는 hash 불변 시 캐시)
    call = result.get("revision_call")

    conn = get_connection()
    conn.execute("""
        UPDATE research_candidates SET status='done',
          revision_call=?, researched_at=datetime('now') WHERE id=?
    """, (json.dumps(call, ensure_ascii=False) if call else None, candidate_id))
    conn.commit()
    conn.close()
    return {"status": "done", "stock_code": stock_code,
            "brief_status": result.get("status"), "revision_call": call,
            "brief": result.get("brief")}


def dismiss_candidate(candidate_id: int) -> dict:
    conn = get_connection()
    conn.execute("UPDATE research_candidates SET status='dismissed' WHERE id=?", (candidate_id,))
    conn.commit()
    conn.close()
    return {"status": "dismissed"}
