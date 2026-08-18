"""전일 국내시장 거래대금 상위 종목 — FinanceDataReader 일별 스냅샷 (D-108).

미국장(us_movers.py)의 국장 대응물. 같은 물음에 답한다: **어제 돈이 어디로 몰렸나**.
차이는 소스와, 종합(sonnet)이 없다는 것 — 표 + 섹터 쏠림까지 전부 **LLM 0콜**로 만든다
(사용자 확정: 국장은 결정적 계산까지. 미국장의 분위기 산문은 국장엔 붙이지 않는다).

소스: `fdr.StockListing("KRX")` 1콜에 거래대금(Amount)·등락률(ChagesRatio)·시장·시총이 다 온다.
pykrx 시장 단위 엔드포인트는 KRX 로그인이 필요해져 쓰지 않는다(ingest_prices.py와 같은 이유).
섹터는 `companies.sector`(KSIC) → `sector_map.group_name`(대분류) 단일 분류체계로 통일 —
industry_groups(큐레이션 119종)와 섞으면 라벨 어휘가 어긋난다.

ETF·리츠·스팩은 제외(사업체가 아니라 담론 대상이 아님). 우선주는 별개 종목으로 세되
섹터는 본주에서 물려받는다(`companies`가 DART corp_code 기반이라 우선주 행이 없다).
"""
import statistics
from datetime import date

from database import get_connection
from services import cache_service

CACHE_KEY = "kr_movers_value"
TTL_SECONDS = 86400          # 24h — 아침 브리핑용 하루 1회 (마감 후 갱신 + 수동 버튼 force)
LIMIT = 20                   # 상위 N 종목
RETAIN_DAYS = 7              # 스냅샷 보존 (신규 진입 판정용)
SOURCE = "fdr-krx-listing"
IDIO_CHANGE = 8.0            # |등락률| 이 이상이면 '거래대금+급등락 동반=실이벤트' (us_briefing과 동일 기준)
CONTRA_MIN_N = 3             # 그룹 역행 판정 최소 클러스터 크기 (2종목짜리 '그룹'은 대표성이 없다)
UNCLASSIFIED = "미분류"

# 사업체가 아닌 상장물 — 이름 기반 제외 (FDR 리스팅에 종류 컬럼이 없다)
_EXCLUDE_TOKENS = ("스팩", "리츠", "ETN", "KODEX", "TIGER", "PLUS", "RISE",
                   "ACE", "SOL ", "KIWOOM", "HANARO", "TIMEFOLIO", "KOSEF", "ARIRANG")


class MoversSourceError(Exception):
    """FDR 응답이 기대 구조와 다름 — 스키마 변경·차단·네트워크 실패 감지."""


def _is_operating_company(name: str) -> bool:
    up = (name or "").upper()
    return not any(tok.upper() in up for tok in _EXCLUDE_TOKENS)


def _fetch_raw() -> tuple[list[dict], str]:
    """FDR KRX 리스팅 → 거래대금 내림차순 상위. 구조가 어긋나면 MoversSourceError."""
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
    except Exception as e:  # noqa: BLE001
        raise MoversSourceError(f"FDR 호출 실패: {type(e).__name__}") from e

    need = {"Code", "Name", "Market", "Close", "Volume", "Amount", "ChagesRatio", "Marcap"}
    missing = need - set(df.columns)
    if missing:
        raise MoversSourceError(f"컬럼 누락 {sorted(missing)} — FDR 스키마 변경 의심")

    df = df[df["Amount"].notna() & df["Close"].notna()]
    df = df.sort_values("Amount", ascending=False)

    rows: list[dict] = []
    for _, r in df.iterrows():
        name = str(r["Name"])
        if not _is_operating_company(name):
            continue
        rows.append({
            "stock_code": str(r["Code"]).zfill(6),
            "name": name,
            "market": str(r["Market"]),
            "close": int(r["Close"]),
            "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else 0,
            "value_traded": int(r["Amount"]),
            "change_pct": round(float(r["ChagesRatio"]), 2),
            "market_cap": int(r["Marcap"]) if r["Marcap"] == r["Marcap"] else None,
        })
        if len(rows) >= LIMIT:
            break
    if not rows:
        raise MoversSourceError("필터 후 종목 0 — 스키마 변경 의심")
    return rows, date.today().isoformat()


def _base_code(code: str) -> str:
    """우선주 → 본주 코드. 우선주는 `companies`(DART corp_code 기반)에 없어 섹터가 비는데,
    본주와 같은 사업을 하므로 본주 섹터를 물려받는 게 맞다 (삼성전자우 005935 → 005930)."""
    return code[:5] + "0" if code[-1] != "0" else code


def _attach_sector(conn, rows: list[dict]) -> None:
    """KSIC → 대분류(sector_map.group_name). 우선주는 본주로 폴백, 그래도 없으면 미분류."""
    codes = {r["stock_code"] for r in rows} | {_base_code(r["stock_code"]) for r in rows}
    ph = ",".join("?" for _ in codes)
    m = {x["stock_code"]: x["grp"] for x in conn.execute(
        f"""SELECT c.stock_code, sm.group_name grp
            FROM companies c JOIN sector_map sm ON sm.sector_name = c.sector
            WHERE c.stock_code IN ({ph})""", sorted(codes))}
    for r in rows:
        code = r["stock_code"]
        r["sector"] = m.get(code) or m.get(_base_code(code)) or UNCLASSIFIED


def _prior_codes(conn, trade_date: str) -> set[str]:
    """직전(오늘 아닌 가장 최근) 스냅샷 종목 — 신규 진입 판정 기준."""
    row = conn.execute(
        "SELECT max(trade_date) d FROM kr_movers WHERE trade_date < ?", (trade_date,)).fetchone()
    if not row or not row["d"]:
        return set()
    return {r["stock_code"] for r in conn.execute(
        "SELECT stock_code FROM kr_movers WHERE trade_date=?", (row["d"],))}


def _read_snapshot(conn, trade_date: str | None = None) -> list[dict]:
    if trade_date is None:
        row = conn.execute("SELECT max(trade_date) d FROM kr_movers").fetchone()
        trade_date = row["d"] if row else None
    if not trade_date:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT trade_date, rank, stock_code, name, market, close, volume, value_traded, "
        "change_pct, sector, market_cap, is_new, fetched_at "
        "FROM kr_movers WHERE trade_date=? ORDER BY rank", (trade_date,))]


def _store(rows: list[dict], trade_date: str) -> None:
    conn = get_connection()
    try:
        prior = _prior_codes(conn, trade_date)
        conn.execute("DELETE FROM kr_movers WHERE trade_date=?", (trade_date,))  # 재적재 멱등
        for i, r in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO kr_movers (trade_date, rank, stock_code, name, market, close, volume, "
                "value_traded, change_pct, sector, market_cap, is_new, fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))",
                (trade_date, i, r["stock_code"], r["name"], r["market"], r["close"], r["volume"],
                 r["value_traded"], r["change_pct"], r["sector"], r["market_cap"],
                 0 if (r["stock_code"] in prior or not prior) else 1))
        for o in conn.execute(
                "SELECT DISTINCT trade_date FROM kr_movers ORDER BY trade_date DESC "
                "LIMIT -1 OFFSET ?", (RETAIN_DAYS,)).fetchall():
            conn.execute("DELETE FROM kr_movers WHERE trade_date=?", (o["trade_date"],))
        conn.commit()
    finally:
        conn.close()


def _clusters(items: list[dict]) -> list[dict]:
    """섹터 쏠림 — 거래대금 비중·대표(중앙값) 등락률. LLM 0.

    '미분류'는 섹터가 아니라 매칭 실패 버킷이라 클러스터로 세지 않는다 —
    묶으면 성격이 제각각인 종목들의 중앙값이 나와 그룹 역행 판정까지 오염시킨다.
    """
    total = sum(i["value_traded"] for i in items) or 1
    by: dict[str, list[dict]] = {}
    for i in items:
        if i["sector"] == UNCLASSIFIED:
            continue
        by.setdefault(i["sector"], []).append(i)
    out = []
    for label, members in by.items():
        chg = [m["change_pct"] for m in members if m["change_pct"] is not None]
        out.append({
            "label": label,
            "n": len(members),
            "value_traded": sum(m["value_traded"] for m in members),
            "share_pct": round(sum(m["value_traded"] for m in members) / total * 100, 1),
            "median_change": round(statistics.median(chg), 1) if chg else 0.0,
            "has_new": any(m["is_new"] for m in members),
            "codes": [m["stock_code"] for m in members],
            "names": [m["name"] for m in members],
        })
    return sorted(out, key=lambda c: c["value_traded"], reverse=True)


def _flag_idiosyncratic(items: list[dict], clusters: list[dict]) -> None:
    """개별 이슈 — 급등락 / 소속 섹터 역행 / 신규 진입. LLM 0 (us_briefing과 동일 규칙)."""
    med = {c["label"]: c["median_change"] for c in clusters}
    size = {c["label"]: c["n"] for c in clusters}
    for m in items:
        flags = []
        ch = m["change_pct"]
        if ch is not None and abs(ch) >= IDIO_CHANGE:
            flags.append(f"{'급등' if ch > 0 else '급락'} {ch:+.1f}%")
        if ch is not None and size.get(m["sector"], 0) >= CONTRA_MIN_N:
            cm = med.get(m["sector"], 0)
            if cm != 0 and (ch > 0) != (cm > 0):    # 부호가 갈릴 때만 '역행'
                flags.append("그룹 역행")
        if m["is_new"]:
            flags.append("신규 진입")
        m["flags"] = flags


def _result(status: str, items: list[dict], error: str | None) -> dict:
    _flagged = list(items)
    clusters = _clusters(_flagged) if _flagged else []
    if _flagged:
        _flag_idiosyncratic(_flagged, clusters)
    return {
        "status": status, "source": SOURCE, "error": error,
        "trade_date": _flagged[0]["trade_date"] if _flagged else None,
        "fetched_at": _flagged[0]["fetched_at"] if _flagged else None,
        "items": _flagged,
        "clusters": clusters,
        "idiosyncratic": [m for m in _flagged if m.get("flags")],
    }


def read_leaders() -> dict:
    """최신 스냅샷 순수 읽기 — 네트워크 없음(일반 로드용, D-100 버튼 주도)."""
    conn = get_connection()
    try:
        return _result("ok", _read_snapshot(conn), None)
    finally:
        conn.close()


def get_leaders(force: bool = False) -> dict:
    """거래대금 상위 — 캐시 우선. status: ok · stale(갱신 실패, 마지막 스냅샷) · error."""
    if not force and cache_service.is_cached(CACHE_KEY):
        cached = read_leaders()
        if cached["items"]:
            return cached

    def _fallback(msg: str) -> dict:
        last = read_leaders()
        return {**last, "status": "stale", "error": msg} if last["items"] \
            else _result("error", [], msg)

    try:
        rows, trade_date = _fetch_raw()
    except MoversSourceError as e:
        return _fallback(str(e))

    conn = get_connection()
    try:
        _attach_sector(conn, rows)
    finally:
        conn.close()

    _store(rows, trade_date)
    cache_service.set_cache(CACHE_KEY, TTL_SECONDS)
    conn = get_connection()
    try:
        return _result("ok", _read_snapshot(conn, trade_date), None)
    finally:
        conn.close()
