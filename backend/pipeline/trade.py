"""수출입(무역) 통계 수집 — 관세청 품목별 수출입실적 (docs/specs/trade-follow.md, D-064 · D-140).

공공데이터포털 data.go.kr 관세청_품목별 수출입실적(GW):
  GET https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList
  params: serviceKey · strtYymm(YYYYMM) · endYymm · hsSgn(HS부호)
  응답: XML — hsCode·statKor(품목명)·year(기간 YYYY.MM)·expDlr(수출$)·expWgt(kg)·impDlr·impWgt·balPayments

D-140에서 별도 프로젝트 data-watcher의 커넥터·수집 규율을 이식했다. 설계를 지배하는 사실:
  ① **조회기간 1년 제한** — 12개월 초과 시 resultCode 99. 캘린더 연 단위로 쪼갠다.
  ② **하위 단위 행이 여럿 온다** — hsSgn을 2·4·6단위로 주면 그 아래 10단위 행 + 연간 누계 행이 섞여 온다.
     period로 합산하고 누계 행(월 없음)은 버린다. 합산을 빼먹으면 품목 총계가 임의의 세부품목 값으로 조용히 대체된다.
  ③ **연속 호출에 429** — 일 10,000 한도와 별개의 순간 속도 제한. 호출 간 최소 간격 + 지수백오프.
  ④ **오류는 두 곳** — 인증·서비스 오류는 cmmMsgHeader/errMsg, 조회 오류는 resultCode. 둘 다 봐야 '빈 결과 위장'을 막는다.
  ⑤ **관세청은 매월 15일경 전월까지를 정정** — 수집은 항상 멱등 upsert, 파생지표는 저장하지 않는다(trade_metrics).
  ⑥ **최신 기간부터 역순, 루프 바깥은 기간** — 첫 패스가 끝나면 전 품목의 최근 데이터가 차서 화면이 쓸 만해진다.
  ⑦ **DB 커넥션을 네트워크 구간에 걸쳐 열어두지 않는다** — 품목 하나 받을 때마다 열고 쓰고 닫는다.

관련 종목은 LLM 논리 지목(compute_beneficiaries) — beneficiary.resolve_and_enrich 재사용(D-036).
"""
import csv
import os
import random
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests

from config import DATA_GO_KR_KEY
from database import get_connection

BASE = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
TIMEOUT = 30
PAGE_SIZE = 1000
MIN_INTERVAL = float(os.getenv("CUSTOMS_MIN_INTERVAL", "0.35"))   # 429 회피 최소 호출 간격(초)
MAX_RETRY = 4
COLLECT_START_YYYYMM = os.getenv("TRADE_COLLECT_START_YYYYMM", "202101")   # YoY의 z에 24개월↑ 필요
WATCHLIST_CSV = Path(os.getenv("TRADE_WATCHLIST_CSV",
                               str(Path(__file__).resolve().parent.parent.parent / "scripts" / "trade_watchlist.local.csv")))

# 기본 팔로우 시드(2026-07-24, 6단위 검증) — 개인 워치리스트 CSV가 없을 때의 최소 세트.
DEFAULT_FOLLOWS = [
    ("854232", "메모리반도체(D램·낸드·HBM)", "반도체"),
    ("854231", "시스템반도체(프로세서·컨트롤러)", "반도체"),
    ("851713", "스마트폰", "IT"),
    ("8524", "디스플레이(평판 모듈)", "IT"),
    ("850760", "전기차용 리튬이온전지", "2차전지"),
    ("8703", "승용자동차", "자동차"),
    ("8708", "자동차부품", "자동차"),
    ("2710", "석유제품", "에너지"),
    ("39", "플라스틱·합성수지", "소재"),
    ("72", "철강", "소재"),
    ("89", "선박", "기계"),
]


class CustomsError(RuntimeError):
    pass


# ── 커넥터 ───────────────────────────────────────────────────────────────────

_gate = threading.Lock()
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    with _gate:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _num(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return 0.0


def _norm_period(raw: str | None) -> str | None:
    """'202501' | '2025.01' | '2025' → 'YYYY-MM'. 월이 없는 연간 누계 행은 None(제외)."""
    if not raw:
        return None
    d = raw.replace(".", "").replace("-", "").strip()
    return f"{d[:4]}-{d[4:]}" if len(d) == 6 and d.isdigit() else None


def _get(params: dict) -> requests.Response:
    """스로틀 + 429/5xx 지수백오프(지터) 재시도. 재시도해도 안 되면 예외 — 조용한 빈 결과 금지."""
    last = None
    for attempt in range(MAX_RETRY):
        _throttle()
        r = requests.get(BASE, params=params, headers={"User-Agent": "explorer-trade/0.2"}, timeout=TIMEOUT)
        if r.status_code == 200:
            return r
        last = r
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep((2 ** attempt) * 0.8 + random.uniform(0, 0.4))
    assert last is not None
    raise CustomsError(f"관세청 API HTTP {last.status_code} (재시도 {MAX_RETRY}회 실패) {last.text[:150]}")


def _request(hs_code: str, strt: str, end: str, page: int = 1) -> ET.Element:
    if not DATA_GO_KR_KEY:
        raise CustomsError("DATA_GO_KR_KEY 미설정 — .env에 공공데이터포털 서비스키 필요")
    r = _get({"serviceKey": DATA_GO_KR_KEY, "strtYymm": strt, "endYymm": end, "hsSgn": hs_code,
              "numOfRows": PAGE_SIZE, "pageNo": page})
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        raise CustomsError(f"XML 파싱 실패 (본문 앞부분: {r.text[:200]!r})") from e
    err = root.findtext(".//errMsg")
    if err:
        raise CustomsError(f"관세청 API: {err} / {root.findtext('.//returnAuthMsg')}")
    code = root.findtext(".//resultCode")
    if code and code.strip() not in ("00", "0"):
        raise CustomsError(f"관세청 API 오류 code={code.strip()} msg={root.findtext('.//resultMsg')}")
    return root


def fetch_window(hs_code: str, strt: str, end: str) -> dict[str, dict]:
    """한 품목·한 연도 window(≤12개월) → {period: 합산}. totalCount가 있으면 페이징을 따라간다."""
    agg: dict[str, dict] = {}
    page, seen = 1, 0
    while True:
        root = _request(hs_code, strt, end, page)
        items = list(root.iter("item"))
        for it in items:
            p = _norm_period(it.findtext("year"))
            if not p:
                continue
            a = agg.setdefault(p, {"export_usd": 0.0, "import_usd": 0.0, "export_wt": 0.0, "import_wt": 0.0})
            a["export_usd"] += _num(it.findtext("expDlr"))
            a["import_usd"] += _num(it.findtext("impDlr"))
            a["export_wt"] += _num(it.findtext("expWgt"))
            a["import_wt"] += _num(it.findtext("impWgt"))
        seen += len(items)
        total = root.findtext(".//totalCount")
        if not items or not total or not total.strip().isdigit() or seen >= int(total.strip()):
            break
        page += 1
    return agg


def _windows(strt: str, end: str) -> list[tuple[str, str]]:
    """조회기간을 캘린더 연 단위(≤12개월)로 분할."""
    sy, sm = int(strt[:4]), int(strt[4:6])
    ey, em = int(end[:4]), int(end[4:6])
    return [(f"{y}{(sm if y == sy else 1):02d}", f"{y}{(em if y == ey else 12):02d}") for y in range(sy, ey + 1)]


def fetch(hs_code: str, strt_yymm: str, end_yymm: str) -> list[dict]:
    """품목 월별 시계열(period 오름차순) — window 분할 후 병합. balance_usd 포함."""
    merged: dict[str, dict] = {}
    for ws, we in _windows(strt_yymm, end_yymm):
        merged.update(fetch_window(hs_code, ws, we))
    return [{"period": p, **v, "balance_usd": v["export_usd"] - v["import_usd"]} for p, v in sorted(merged.items())]


def item_name(hs_code: str, strt: str = "202501", end: str = "202502") -> str | None:
    """관세청이 부르는 품목명(statKor) — 워치리스트 라벨과 대조해 HS 오기를 잡는다."""
    for it in _request(hs_code, strt, end).iter("item"):
        v = (it.findtext("statKor") or "").strip()
        if v and v != "-":
            return v
    return None


def probe(hs_code: str = "8542", strt_yymm: str = "202501", end_yymm: str = "202506") -> str:
    """응답 원본 앞부분 — 필드명·오류메시지 확인용(파싱 전 진단)."""
    r = _get({"serviceKey": DATA_GO_KR_KEY, "strtYymm": strt_yymm, "endYymm": end_yymm, "hsSgn": hs_code})
    return f"HTTP {r.status_code}\n{r.text[:2000]}"


def latest_available_period(hs_code: str = "8542") -> str | None:
    """원천의 최신 월을 1콜로 확인 — 신선도 폴링용. 현행화가 '15일경'이라 달력만 믿으면 하루 어긋난다."""
    t = date.today()
    got = fetch_window(hs_code, f"{t.year}01", f"{t.year}{t.month:02d}")
    return max(got) if got else None


# ── 워치리스트 ────────────────────────────────────────────────────────────────

def read_watchlist_csv(path: Path | None = None) -> list[dict]:
    """개인 워치리스트 CSV(hs_code,item_name,group_label; '#' 주석 허용) → 행 목록. 엑셀 선행 0 유실 보정."""
    path = path or WATCHLIST_CSV
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    out = []
    for r in csv.DictReader(lines):
        hs = (r.get("hs_code") or "").strip()
        if not hs:
            continue
        if hs.isdigit() and len(hs) % 2 == 1:
            hs = hs.zfill(len(hs) + 1)
        out.append({"hs_code": hs, "item_name": (r.get("item_name") or hs).strip(),
                    "group_label": (r.get("group_label") or "").strip() or "미분류"})
    return out


def seed_watchlist(path: Path | None = None) -> dict:
    """CSV → trade_follow 멱등 반영(이름·그룹 갱신, 신규 추가). CSV에 없는 기존 품목은 건드리지 않는다
    (기본 세트·UI에서 추가한 팔로우가 공존)."""
    items = read_watchlist_csv(path)
    if not items:
        return {"seeded": 0, "note": f"CSV 없음: {path or WATCHLIST_CSV}"}
    conn = get_connection()
    n_new = 0
    for it in items:
        cur = conn.execute(
            "INSERT INTO trade_follow (hs_code, item_name, group_label, active) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(hs_code) DO UPDATE SET item_name=excluded.item_name, group_label=excluded.group_label, active=1",
            (it["hs_code"], it["item_name"], it["group_label"]))
        n_new += 1 if cur.rowcount == 1 else 0
    conn.commit()
    conn.close()
    return {"seeded": len(items), "source": str(path or WATCHLIST_CSV)}


def seed_default_follows() -> int:
    conn = get_connection()
    n = 0
    for hs, name, group in DEFAULT_FOLLOWS:
        n += conn.execute("INSERT OR IGNORE INTO trade_follow (hs_code, item_name, group_label) VALUES (?, ?, ?)",
                          (hs, name, group)).rowcount
    conn.commit()
    conn.close()
    return n


def _followed(only: list[str] | None = None) -> list[dict]:
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT hs_code, item_name, group_label FROM trade_follow WHERE active=1 ORDER BY group_label, hs_code")]
    conn.close()
    return [r for r in rows if not only or r["hs_code"] in only]


# ── 수집 ─────────────────────────────────────────────────────────────────────

UPSERT = """
INSERT INTO trade_stats (hs_code, period, export_usd, import_usd, export_wt, import_wt, balance_usd)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(hs_code, period) DO UPDATE SET
  export_usd=excluded.export_usd, import_usd=excluded.import_usd, export_wt=excluded.export_wt,
  import_wt=excluded.import_wt, balance_usd=excluded.balance_usd, fetched_at=datetime('now')
"""


def _log(msg: str) -> None:
    print(msg, flush=True)   # launchd 리다이렉트 시 블록 버퍼링 — flush 없으면 종료까지 0바이트


def collect_followed(only: list[str] | None = None, strt_yymm: str | None = None,
                     end_yymm: str | None = None, progress=_log) -> dict:
    """팔로우 품목 × 기간을 **최신 window부터 역순**으로 수집(멱등 upsert). 품목 단위 실패는 삼키고 계속하되
    결과에 failed·errors를 남겨 collect_status()가 error/partial을 판정한다."""
    items = _followed(only)
    if not items:
        return {"items": 0, "stored_rows": 0, "failed": 0, "windows": 0, "note": "팔로우 비어 있음"}
    t = date.today()
    strt = strt_yymm or COLLECT_START_YYYYMM
    end = end_yymm or f"{t.year}{t.month:02d}"
    windows = list(reversed(_windows(strt, end)))
    stored, failed, errors = 0, 0, []
    failed_codes: set[str] = set()
    for wi, (ws, we) in enumerate(windows, 1):
        w_rows, w_failed = 0, 0
        for n, it in enumerate(items, 1):
            hs = it["hs_code"]
            try:
                rows = fetch(hs, ws, we)                       # 네트워크 — 트랜잭션 밖
            except Exception as e:  # noqa: BLE001
                w_failed += 1
                failed_codes.add(hs)
                if len(errors) < 20:
                    errors.append(f"{ws}~{we} {hs} {it['item_name']}: {type(e).__name__} {e}"[:200])
                continue
            if rows:
                conn = get_connection()                        # 쓰기 순간에만 연다
                conn.executemany(UPSERT, [(hs, r["period"], r["export_usd"], r["import_usd"],
                                           r["export_wt"], r["import_wt"], r["balance_usd"]) for r in rows])
                conn.commit()
                conn.close()
            w_rows += len(rows)
            if n % 40 == 0:
                progress(f"[trade]   {ws}~{we} {n}/{len(items)}품목")
        stored += w_rows
        failed += w_failed
        progress(f"[trade] window {wi}/{len(windows)} {ws}~{we} — {w_rows}행 · 실패 {w_failed}")
    out = {"items": len(items), "stored_rows": stored, "failed": failed, "windows": len(windows),
           "range": f"{strt}~{end} (최신부터 역순)", "failed_items": len(failed_codes)}
    if errors:
        out["errors"] = errors[:5]
    return out


def collect_status(r: dict | None) -> str:
    """수집 결과 → 잡 상태. 한 행도 못 넣었으면 실패다(예외가 안 났더라도)."""
    if not r:
        return "skipped"
    if r.get("items") == 0:
        return "noop"
    if r.get("failed") and not r.get("stored_rows"):
        return "error"
    if r.get("failed"):
        return "partial"
    return "ok"


def latest_stored_period() -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT MAX(period) p FROM trade_stats").fetchone()
    conn.close()
    return row["p"] if row else None


# ── 관련 종목 (LLM 논리 지목, D-036) ─────────────────────────────────────────

_BENE_PROMPT = """다음은 한국의 수출입 품목 '{item}'(HS {hs})의 최근 월별 수출 추이다.
{trend}

이 품목의 수출 증감이 **인과 논리로** 수혜/피해를 주는 한국 상장 종목을 지목하라.
문서 언급 빈도가 아니라 인과 논리로 판단 — 아직 회자 안 됐어도 논리상 수혜/피해면 지목.
(예: 이 품목 수출↑ → 생산·소재·장비 밸류체인 수혜 / 원재료 수입 의존 종목은 피해 가능)
논리로 근거 댈 수 있는 것만, 억지 금지, 최대 6개.

JSON만: {{"beneficiaries":[{{"name":"정확한 상장사명","rel":"수혜" 또는 "피해","reason":"이 품목 추이가 왜 이 종목에 수혜/피해인지 한 문장"}}]}}"""


def _trend_str(stats: list) -> str:
    if not stats:
        return "(데이터 없음)"
    s = sorted(stats, key=lambda r: r["period"])
    recent, first = s[-1], s[0]
    yoy = ""
    if len(s) >= 13 and s[-13]["export_usd"]:
        yoy = f", 전년동월대비 {(recent['export_usd'] / s[-13]['export_usd'] - 1) * 100:+.0f}%"
    return (f"수출: {first['period']} ${first['export_usd'] / 1e9:.1f}B → {recent['period']} ${recent['export_usd'] / 1e9:.1f}B{yoy} "
            f"(무역수지 {recent['period']} ${(recent['balance_usd'] or 0) / 1e9:+.1f}B)")


def compute_beneficiaries(hs_code: str) -> list[dict]:
    """품목 관련 종목을 LLM 논리로 지목 → resolve_and_enrich → trade_beneficiaries 캐시(멱등 교체)."""
    import json
    from pipeline.enrich import _call_claude_code, llm_available
    conn = get_connection()
    item = conn.execute("SELECT item_name FROM trade_follow WHERE hs_code=?", (hs_code,)).fetchone()
    stats = conn.execute("SELECT period, export_usd, balance_usd FROM trade_stats WHERE hs_code=? ORDER BY period DESC LIMIT 13",
                         (hs_code,)).fetchall()
    if not item or not llm_available():
        conn.close()
        return []
    try:
        raw = _call_claude_code(_BENE_PROMPT.format(item=item["item_name"], hs=hs_code, trend=_trend_str(stats)),
                                model="sonnet", timeout=180)
        picks = json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("beneficiaries") or []
    except Exception as e:  # noqa: BLE001
        print(f"[trade] {hs_code} beneficiaries 실패: {e}")
        conn.close()
        return []
    from pipeline.beneficiary import resolve_and_enrich
    enriched = resolve_and_enrich(conn, [p for p in picks if isinstance(p, dict)])
    conn.execute("DELETE FROM trade_beneficiaries WHERE hs_code=?", (hs_code,))
    for b in enriched:
        conn.execute(
            "INSERT OR IGNORE INTO trade_beneficiaries (hs_code, stock_code, name, rel, reason, rs, per, mktcap, pos_52w, in_universe, universe_groups) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hs_code, b.get("stock_code"), b.get("name"), b.get("rel"), b.get("reason"), b.get("rs_short"), b.get("per"),
             b.get("market_cap"), b.get("pos_52w"), 1 if b.get("in_universe") else 0,
             json.dumps(b.get("universe_groups") or [], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return enriched
