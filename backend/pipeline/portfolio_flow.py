"""포트폴리오 자료 흐름 — 보유 종목이 팔로우 자료에서 어떻게 이야기되나 (docs/specs/portfolio-intelligence.md §3).

  언급 급증 — 오늘(KST) 언급 문서 ≥ 3 이고 직전 7일 평균의 2배 이상 (signals.mention_surge와 같은 기준)
  논조 변화 — 오늘 연결 문서의 부정 비율이 직전 7일보다 30%p 이상 높을 때 (문서 enrichments.sentiment, 오늘 2건 이상)
  요약     — 그날 1D 다이제스트의 insights(새로 나온 것). 보유 종목은 상위 5개 밖이어도 새 문서가 있는 날 만든다
집계는 결정적. 요약 생성만 LLM(haiku, 문서 집합이 같으면 재생성 안 함).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
DAYS = 14
SURGE_MIN, SURGE_X = 3, 2.0
TONE_MIN_DOCS, TONE_JUMP = 2, 0.30


def _utc(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(timezone.utc).isoformat()


def daily(conn: sqlite3.Connection, entity_id: int, today: date) -> list[dict]:
    """최근 14일(KST) 날짜별 언급 문서 수·긍정·부정."""
    start = today - timedelta(days=DAYS - 1)
    rows = conn.execute(
        "SELECT rd.published_at, en.sentiment FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id "
        "LEFT JOIN enrichments en ON en.doc_id=rd.id WHERE el.link_type='stock' AND el.entity_id=? "
        "AND rd.published_at >= ? AND rd.published_at < ? GROUP BY rd.id",
        (entity_id, _utc(start), _utc(today + timedelta(days=1)))).fetchall()
    by = {(start + timedelta(days=i)).isoformat(): {"date": (start + timedelta(days=i)).isoformat(), "n": 0, "pos": 0, "neg": 0}
          for i in range(DAYS)}
    for r in rows:
        day = datetime.fromisoformat(r["published_at"]).astimezone(KST).date().isoformat()
        if day in by:
            by[day]["n"] += 1
            if r["sentiment"] == "positive":
                by[day]["pos"] += 1
            elif r["sentiment"] == "negative":
                by[day]["neg"] += 1
    return list(by.values())


def judge(series: list[dict]) -> dict:
    today, prev = series[-1], series[-8:-1]
    avg7 = sum(d["n"] for d in prev) / 7
    surge = today["n"] >= SURGE_MIN and today["n"] >= SURGE_X * max(avg7, 0.5)
    prev_n = sum(d["n"] for d in prev)
    neg_today = today["neg"] / today["n"] if today["n"] else None
    neg_prev = sum(d["neg"] for d in prev) / prev_n if prev_n else 0.0
    tone = today["n"] >= TONE_MIN_DOCS and neg_today is not None and neg_today - neg_prev >= TONE_JUMP
    return {"today": today["n"], "avg7": round(avg7, 1), "surge": surge, "tone_shift": tone,
            "neg_today_pct": round(neg_today * 100) if neg_today is not None else None, "neg_prev_pct": round(neg_prev * 100)}


def latest_digest(conn: sqlite3.Connection, entity_id: int) -> dict | None:
    r = conn.execute("SELECT period_start, insights, digest, doc_count FROM entity_digests WHERE entity_id=? AND period='1d' "
                     "ORDER BY period_start DESC LIMIT 1", (entity_id,)).fetchone()
    if not r:
        return None
    first = next((ln.strip(" -#*") for ln in (r["digest"] or "").splitlines() if ln.strip(" -#*")), "")
    return {"date": r["period_start"], "insights": (r["insights"] or "").strip() or None, "lead": first[:200] or None, "docs": r["doc_count"]}


def flow(conn: sqlite3.Connection, holdings: list[dict], today: date) -> list[dict]:
    from pipeline.portfolio_exposure import company_entity
    out = []
    for h in holdings:
        ent = company_entity(conn, h["code"])
        if not ent:
            out.append({"code": h["code"], "name": h["name"], "series": [], "digest": None, **judge([{"n": 0, "pos": 0, "neg": 0}] * 8)})
            continue
        series = daily(conn, ent["id"], today)
        out.append({"code": h["code"], "name": h["name"], "series": series, "digest": latest_digest(conn, ent["id"]), **judge(series)})
    return out


def ensure_digests(holdings: list[dict], today: date, flows: list[dict]) -> dict:
    """오늘 새 문서가 있는 보유 종목만 1D 다이제스트 생성(상위 5개 밖 소형주 보완). 같은 문서 집합이면 재생성 안 함."""
    from pipeline.digests import compute_daily
    stats = {}
    for f in flows:
        if f["today"]:
            r = compute_daily(today.isoformat(), stock_code=f["code"])
            stats[f["code"]] = {k: v for k, v in r.items() if k in ("generated", "unchanged", "failed", "skipped") and v}
    return stats


def summary_lines(flows: list[dict], today: date) -> list[str]:
    """일일 요약에 붙일 줄 — 급증·논조 변화가 있거나 오늘 요약의 '새로운 점'이 있는 종목만."""
    lines = []
    for f in flows:
        tags = []
        if f["surge"]:
            tags.append(f"언급 급증 {f['today']}건(7일 평균 {f['avg7']})")
        if f["tone_shift"]:
            tags.append(f"부정 비율 {f['neg_prev_pct']}%→{f['neg_today_pct']}%")
        d = f["digest"]
        new = d["insights"] if d and d["date"] == today.isoformat() and d["insights"] else None
        if tags or new:
            lines.append(f"· {f['name']}: {' · '.join(tags)}" + (f"{' — ' if tags else ''}{new[:160]}" if new else ""))
    return lines
