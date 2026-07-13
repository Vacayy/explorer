"""실시간 시세 코어 — 네이버 폴링 API (지연 0). 라우터·RAG 공용.

수집 저장 없음 — 조회 시점 프록시 (10초 인메모리 캐시).
"""
import time

import requests

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_API = "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
_TTL = 10
_cache: dict[str, tuple[float, list[dict]]] = {}


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_quotes(codes: list[str]) -> list[dict]:
    key = ",".join(sorted(set(c.strip() for c in codes if c and c.strip())))[:400]
    if not key:
        return []
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    try:
        r = requests.get(_API.format(codes=key), headers=_UA, timeout=10)
        r.raise_for_status()
        datas = r.json().get("datas") or []
    except Exception:
        return hit[1] if hit else []
    out = [{
        "stock_code": d.get("itemCode", ""),
        "price": _num(d.get("closePrice")),
        "change": _num(d.get("compareToPreviousClosePrice")),
        "change_pct": _num(d.get("fluctuationsRatio")),
        "volume": _num(d.get("accumulatedTradingVolume")),
        "market_status": d.get("marketStatus"),
        "traded_at": d.get("localTradedAt"),
    } for d in datas]
    _cache[key] = (now, out)
    return out


def quote_block(conn, text: str, limit: int = 3) -> str:
    """질문에 언급된 종목의 실시간 시세 블록 — AI 답변이 낡은 종가로 말하지 않게."""
    rows = conn.execute(
        "SELECT name, aliases FROM entities WHERE type='company' AND aliases IS NOT NULL").fetchall()
    # 긴 이름 우선 + 매칭된 구간 소비 — 'SK하이닉스' 안의 '이닉스'/'SK' 오탐 방지 (실측)
    named = []
    work = text
    for r in sorted(rows, key=lambda r: -len(r["name"] or "")):
        if len(named) >= limit:
            break
        if r["name"] and len(r["name"]) >= 2 and r["name"] in work:
            named.append((r["name"], r["aliases"]))
            work = work.replace(r["name"], " ")
    if not named:
        return ""
    quotes = {q["stock_code"]: q for q in fetch_quotes([c for _, c in named])}
    lines = []
    for name, code in named:
        q = quotes.get(code)
        if not q or q["price"] is None:
            continue
        status = " · 장중" if q.get("market_status") == "OPEN" else ""
        lines.append(f"- {name}: {q['price']:,.0f}원 ({q['change_pct']:+.1f}%){status}")
    if not lines:
        return ""
    return "\n[실시간 시세 — 답변 시점 기준. 문서 속 가격과 다르면 이쪽이 최신]\n" + "\n".join(lines)
