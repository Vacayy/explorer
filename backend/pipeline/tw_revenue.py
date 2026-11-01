"""대만 월매출 — 92개사(pipeline/tw_universe) 월별 매출·MoM·YoY (docs/specs/tw-revenue.md, LLM 0).

대만 상장사는 매달 10일까지 전월 매출을 MOPS(公開資訊觀測站)에 공시해야 한다. 원천은 두 갈래다.
- 최신 월: TWSE Open API(상장) + TPEx Open API(장외). JSON, 키 없음.
- 과거 월: MOPS 월별 요약 HTML `nas/t21/{sii|otc}/t21sc03_{민국년}_{월}_{0|1}.html` (0=국내, 1=외국 KY 법인), Big5.
단위는 천 대만달러(원천 그대로). 날짜는 민국 연도(115 = 2026)를 YYYY-MM으로 바꿔 저장한다.
월매출은 회사마다 1~10일 사이에 올라오므로 매일 최신 월을 다시 받아 덮어쓴다(멱등 upsert).
"""
import re
import time
from datetime import date

from database import get_connection
from pipeline.tw_universe import CODES

TWSE_API = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_API = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
MOPS = "https://mopsov.twse.com.tw/nas/t21/{board}/t21sc03_{roc}_{month}_{kind}.html"
UA = {"User-Agent": "Mozilla/5.0"}
FIELDS = ("revenue", "prev_month", "last_year", "mom_pct", "yoy_pct", "cum", "cum_last_year", "cum_pct")


def roc_to_ym(roc: str) -> str:
    """'11509' → '2026-09'"""
    roc = str(roc).strip()
    return f"{int(roc[:-2]) + 1911}-{int(roc[-2:]):02d}"


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "--", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _note(v) -> str | None:
    s = (v or "").strip()
    return None if s in ("", "-", "--") else s


def parse_openapi(rows: list[dict], market: str) -> list[dict]:
    keys = ("營業收入-當月營收", "營業收入-上月營收", "營業收入-去年當月營收", "營業收入-上月比較增減(%)",
            "營業收入-去年同月增減(%)", "累計營業收入-當月累計營收", "累計營業收入-去年累計營收", "累計營業收入-前期比較增減(%)")
    out = []
    for r in rows:
        code = str(r.get("公司代號", "")).strip()
        if code not in CODES or not r.get("資料年月"):
            continue
        out.append({"code": code, "ym": roc_to_ym(r["資料年月"]), "name_zh": r.get("公司名稱"), "market": market,
                    **{f: _num(r.get(k)) for f, k in zip(FIELDS, keys)},
                    "note": _note(r.get("備註")), "source": "openapi"})
    return out


_ROW = re.compile(r"<tr align=right>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)


def parse_mops(html: str, ym: str, market: str) -> list[dict]:
    """월별 요약 표의 행(코드·이름·당월·전월·전년 동월·MoM%·YoY%·누적·전년 누적·누적%·비고)"""
    out = []
    for row in _ROW.findall(html):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in _CELL.findall(row)]
        if len(cells) < 10 or cells[0] not in CODES:
            continue
        out.append({"code": cells[0], "ym": ym, "name_zh": cells[1], "market": market,
                    **{f: _num(v) for f, v in zip(FIELDS, cells[2:10])},
                    "note": _note(cells[10] if len(cells) > 10 else None), "source": "mops"})
    return out


def _upsert(conn, recs: list[dict]) -> int:
    for r in recs:
        conn.execute(
            "INSERT INTO tw_monthly_revenue (code, ym, name_zh, market, revenue, prev_month, last_year, mom_pct, yoy_pct, "
            "cum, cum_last_year, cum_pct, note, source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now')) "
            "ON CONFLICT(code, ym) DO UPDATE SET name_zh=excluded.name_zh, market=excluded.market, revenue=excluded.revenue, "
            "prev_month=excluded.prev_month, last_year=excluded.last_year, mom_pct=excluded.mom_pct, yoy_pct=excluded.yoy_pct, "
            "cum=excluded.cum, cum_last_year=excluded.cum_last_year, cum_pct=excluded.cum_pct, note=excluded.note, "
            "source=excluded.source, fetched_at=excluded.fetched_at",
            (r["code"], r["ym"], r["name_zh"], r["market"], *[r[f] for f in FIELDS], r["note"], r["source"]))
    return len(recs)


def fetch_latest() -> dict:
    """최신 월 — 두 Open API. 하나라도 실패하면 예외(조용히 반쪽만 저장하지 않는다)"""
    import requests
    recs = []
    for url, market in ((TWSE_API, "TWSE"), (TPEX_API, "TPEx")):
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        recs += parse_openapi(r.json(), market)
    conn = get_connection()
    try:
        n = _upsert(conn, recs)
        conn.commit()
    finally:
        conn.close()
    months = sorted({r["ym"] for r in recs})
    missing = sorted(CODES - {r["code"] for r in recs if r["ym"] == (months[-1] if months else None)})
    return {"stored": n, "ym": months[-1] if months else None, "missing": missing,
            "status": "error" if not recs else "partial" if missing else "ok"}


def fetch_month(year: int, month: int, pause: float = 4.0) -> list[dict]:
    """과거 한 달 — MOPS 4페이지(상장·장외 × 국내·외국). 페이지 실패는 예외로 올린다"""
    import requests
    roc, ym, recs = year - 1911, f"{year}-{month:02d}", []
    for board, market in (("sii", "TWSE"), ("otc", "TPEx")):
        for kind in (0, 1):
            # MOPS는 연속 요청이 길어지면 연결을 끊는다(2026-10-18, 20개월 뒤 ConnectionError 연속) — 쉬었다 세 번까지
            for attempt in range(3):
                try:
                    r = requests.get(MOPS.format(board=board, roc=roc, month=month, kind=kind), headers=UA, timeout=40)
                    r.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise
                    time.sleep(30 * (attempt + 1))
            recs += parse_mops(r.content.decode("big5", errors="ignore"), ym, market)
            time.sleep(pause)            # MOPS는 빠른 연속 요청을 막는다
    return recs


def backfill(months: int = 36, today: date | None = None, pause: float = 4.0, require: set[str] | None = None) -> dict:
    """최근 months개월(이번 달 제외)을 채운다. 이어 받기: 이미 85개사 이상 있는 달은 건너뛴다.
    require를 주면 그 회사들이 모두 있는 달만 건너뛴다 — 대상에 새 회사를 넣고 과거분을 채울 때."""
    today = today or date.today()
    y, m = today.year, today.month
    done, skipped, failed = [], [], []
    conn = get_connection()
    try:
        for _ in range(months):
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
            ym = f"{y}-{m:02d}"
            if require:
                ph = ",".join("?" * len(require))
                have_req = conn.execute(f"SELECT COUNT(*) FROM tw_monthly_revenue WHERE ym=? AND code IN ({ph})", (ym, *require)).fetchone()[0]
                done_month = have_req == len(require)
            else:
                done_month = conn.execute("SELECT COUNT(*) FROM tw_monthly_revenue WHERE ym=?", (ym,)).fetchone()[0] >= 85
            if done_month:
                skipped.append(ym)
                continue
            try:
                recs = fetch_month(y, m, pause)
            except Exception as e:  # noqa: BLE001 — 한 달 실패는 남기고 다음 달로
                failed.append(f"{ym}: {type(e).__name__}")
                continue
            _upsert(conn, recs)
            conn.commit()
            done.append(f"{ym}:{len(recs)}")
    finally:
        conn.close()
    return {"filled": done, "skipped": len(skipped), "failed": failed,
            "status": "error" if failed and not done else "partial" if failed else "ok"}


def _three_month_yoy(series: list[dict]) -> float | None:
    """최근 3개월 합 / 전년 같은 3개월 합 − 1 (%) — 월별 변동이 큰 회사의 추세용"""
    if len(series) < 3:
        return None
    last3 = series[-3:]
    cur = [p["revenue"] for p in last3]
    prev = [p["last_year"] for p in last3]
    if None in cur or None in prev or not sum(prev):
        return None
    return round((sum(cur) / sum(prev) - 1) * 100, 1)


def read(months: int = 36) -> dict:
    """화면용 — 층별 회사 + 최근 months개월 시계열(LLM·네트워크 0)"""
    from pipeline.tw_universe import COMPANIES, LAYERS
    conn = get_connection()
    try:
        rows = conn.execute("SELECT code, ym, market, revenue, last_year, mom_pct, yoy_pct, note, fetched_at "
                            "FROM tw_monthly_revenue ORDER BY ym").fetchall()
        latest = conn.execute("SELECT MAX(ym), MAX(fetched_at) FROM tw_monthly_revenue").fetchone()
    finally:
        conn.close()
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["code"], []).append(dict(r))
    as_of = latest[0]
    items = []
    for code, name, layer, role in COMPANIES:
        s = by.get(code, [])[-months:]
        last = s[-1] if s else None
        items.append({
            "code": code, "name": name, "layer": layer, "role": role, "market": last["market"] if last else None,
            "ym": last["ym"] if last else None, "revenue": last["revenue"] if last else None,
            "yoy_pct": last["yoy_pct"] if last else None, "mom_pct": last["mom_pct"] if last else None,
            "yoy_3m": _three_month_yoy(s), "lagging": bool(last and as_of and last["ym"] < as_of),
            "note": last["note"] if last else None,
            "series": [{"ym": p["ym"], "revenue": p["revenue"], "yoy_pct": p["yoy_pct"]} for p in s],
        })
    reported = sum(1 for i in items if i["ym"] == as_of)
    return {"as_of": as_of, "fetched_at": latest[1], "reported": reported, "total": len(items),
            "layers": [{"key": k, "label": v} for k, v in LAYERS], "items": items}
