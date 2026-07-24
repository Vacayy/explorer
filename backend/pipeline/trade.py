"""수출입(무역) 통계 수집 — 관세청 품목별 수출입실적 (docs/specs/trade-follow.md).

공공데이터포털 data.go.kr 관세청_품목별 수출입실적(GW):
  GET http://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList
  params: serviceKey · strtYymm(YYYYMM) · endYymm · hsSgn(HS부호)
  응답: XML — hsCd·statKor(품목명)·year(기간)·expDlr(수출$)·expWgt(kg)·impDlr·impWgt·balPayments(무역수지)
  ※ 응답 필드명은 첫 라이브 호출(probe)로 확정 — 방어적 파싱 + raw 보존.

관련 종목은 LLM 논리 지목(compute_beneficiaries) — beneficiary.resolve_and_enrich 재사용(D-036).
"""
import xml.etree.ElementTree as ET

import requests

from config import DATA_GO_KR_KEY
from database import get_connection

BASE = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"

# 기본 팔로우 시드 (2026-07-24, 관세청 API로 6단위 검증·수출액순) — HS부호·품목명.
# 관련 종목은 런타임 LLM 지목. 6단위는 투자 서사 직결처(반도체 메모리/시스템·EV전지·스마트폰),
# 세분이 흐리는 광범위 카테고리는 2·4단위 유지(거짓 정밀 회피).
DEFAULT_FOLLOWS = [
    ("854232", "메모리반도체(D램·낸드·HBM)", "반도체"),      # 월 ~$8B, 한국 최대 수출
    ("854231", "시스템반도체(프로세서·컨트롤러)", "반도체"),   # 월 ~$3B
    ("851713", "스마트폰", "IT"),
    ("8524", "디스플레이(평판 모듈)", "IT"),               # 6단위 세분 모호 → 4단위
    ("850760", "전기차용 리튬이온전지", "2차전지"),          # EV 배터리 (LG엔솔·삼성SDI)
    ("8703", "승용자동차", "자동차"),                      # 세분(배기량·HEV·EV)은 후속
    ("8708", "자동차부품", "자동차"),
    ("2710", "석유제품", "에너지"),
    ("39", "플라스틱·합성수지", "소재"),                    # 2단위=석화 전체
    ("72", "철강", "소재"),
    ("89", "선박", "기계"),
]

# 응답 필드 (2026-07-24 라이브 확정): expDlr·impDlr·expWgt·impWgt·balPayments·hsCode·statKor·year(YYYY.MM)
_F = {
    "period": ("year",),
    "export_usd": ("expDlr",),
    "import_usd": ("impDlr",),
    "export_wt": ("expWgt",),
    "import_wt": ("impWgt",),
    "hs": ("hsCode",),
    "name": ("statKor",),
}


def _pick(el: ET.Element, keys: tuple) -> str | None:
    for k in keys:
        v = el.findtext(k)
        if v not in (None, ""):
            return v.strip()
    return None


def _num(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def _norm_period(raw: str | None) -> str | None:
    """'202501' | '2025.01' | '2025' → 'YYYY-MM'. 총계/누계 행(월 없음)은 None으로 스킵."""
    if not raw:
        return None
    d = raw.replace(".", "").replace("-", "").strip()
    if len(d) == 6 and d.isdigit():
        return f"{d[:4]}-{d[4:]}"
    return None   # 연간 총계 등은 추이에서 제외


def fetch(hs_code: str, strt_yymm: str, end_yymm: str) -> list[dict]:
    """관세청 품목별 수출입실적 조회 → **기간별 합산** 월별 시계열.
    hsSgn을 2·4·6단위로 주면 하위 10단위 행이 여럿 오므로 period 기준 합산해 품목 총계를 낸다."""
    if not DATA_GO_KR_KEY:
        raise RuntimeError("DATA_GO_KR_KEY 미설정 — .env에 공공데이터포털 서비스키 필요")
    r = requests.get(BASE, params={
        "serviceKey": DATA_GO_KR_KEY, "strtYymm": strt_yymm, "endYymm": end_yymm, "hsSgn": hs_code},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    code = root.findtext(".//resultCode")
    if code and code not in ("00", "0"):   # 99=기간초과 등 — 조용히 빈 결과 처리 방지
        raise RuntimeError(f"관세청 API: {root.findtext('.//resultMsg')} (code {code})")
    agg: dict[str, dict] = {}
    for item in root.iter("item"):
        period = _norm_period(_pick(item, _F["period"]))
        if not period:
            continue   # 연간 누계 행 등 제외
        a = agg.setdefault(period, {"export_usd": 0.0, "import_usd": 0.0, "export_wt": 0.0, "import_wt": 0.0})
        a["export_usd"] += _num(_pick(item, _F["export_usd"])) or 0
        a["import_usd"] += _num(_pick(item, _F["import_usd"])) or 0
        a["export_wt"] += _num(_pick(item, _F["export_wt"])) or 0
        a["import_wt"] += _num(_pick(item, _F["import_wt"])) or 0
    return [{"period": p, **v, "balance_usd": v["export_usd"] - v["import_usd"]}
            for p, v in sorted(agg.items())]


def probe(hs_code: str = "8542", strt_yymm: str = "202501", end_yymm: str = "202506") -> str:
    """첫 라이브 확인용 — 원본 XML 앞부분 반환(응답 필드명 확정). 파싱 전 진단."""
    r = requests.get(BASE, params={
        "serviceKey": DATA_GO_KR_KEY, "strtYymm": strt_yymm, "endYymm": end_yymm, "hsSgn": hs_code},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    return f"HTTP {r.status_code}\n{r.text[:2000]}"


def seed_default_follows() -> int:
    conn = get_connection()
    n = 0
    for hs, name, group in DEFAULT_FOLLOWS:
        cur = conn.execute(
            "INSERT OR IGNORE INTO trade_follow (hs_code, item_name, group_label) VALUES (?, ?, ?)",
            (hs, name, group))
        n += cur.rowcount
    conn.commit()
    conn.close()
    return n


_BENE_PROMPT = """다음은 한국의 수출입 품목 '{item}'(HS {hs})의 최근 월별 수출 추이다.
{trend}

이 품목의 수출 증감이 **인과 논리로** 수혜/피해를 주는 한국 상장 종목을 지목하라.
문서 언급 빈도가 아니라 인과 논리로 판단 — 아직 회자 안 됐어도 논리상 수혜/피해면 지목.
(예: 이 품목 수출↑ → 생산·소재·장비 밸류체인 수혜 / 원재료 수입 의존 종목은 피해 가능)
논리로 근거 댈 수 있는 것만, 억지 금지, 최대 6개.

JSON만: {{"beneficiaries":[{{"name":"정확한 상장사명","rel":"수혜" 또는 "피해","reason":"이 품목 추이가 왜 이 종목에 수혜/피해인지 한 문장"}}]}}"""


def _trend_str(stats: list) -> str:
    """최근 통계로 추이 요약 문자열 (LLM 입력)."""
    if not stats:
        return "(데이터 없음)"
    s = sorted(stats, key=lambda r: r["period"])
    recent = s[-1]; first = s[0]
    yoy = ""
    if len(s) >= 13:
        prev = s[-13]
        if prev["export_usd"]:
            yoy = f", 전년동월대비 {(recent['export_usd']/prev['export_usd']-1)*100:+.0f}%"
    return (f"수출: {first['period']} ${first['export_usd']/1e9:.1f}B → "
            f"{recent['period']} ${recent['export_usd']/1e9:.1f}B{yoy} "
            f"(무역수지 {recent['period']} ${recent['balance_usd']/1e9:+.1f}B)")


def compute_beneficiaries(hs_code: str) -> list[dict]:
    """품목 관련 종목을 LLM 논리로 지목(D-036) → resolve_and_enrich → trade_beneficiaries 캐시(멱등 교체)."""
    import json
    from pipeline.enrich import _call_claude_code, llm_available
    conn = get_connection()
    item = conn.execute("SELECT item_name FROM trade_follow WHERE hs_code=?", (hs_code,)).fetchone()
    stats = conn.execute(
        "SELECT period, export_usd, balance_usd FROM trade_stats WHERE hs_code=? ORDER BY period DESC LIMIT 13",
        (hs_code,)).fetchall()
    if not item or not llm_available():
        conn.close()
        return []
    try:
        raw = _call_claude_code(
            _BENE_PROMPT.format(item=item["item_name"], hs=hs_code, trend=_trend_str(stats)),
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
            "INSERT OR IGNORE INTO trade_beneficiaries (hs_code, stock_code, name, rel, reason, "
            "rs, per, mktcap, pos_52w, in_universe, universe_groups) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hs_code, b.get("stock_code"), b.get("name"), b.get("rel"), b.get("reason"),
             b.get("rs_short"), b.get("per"), b.get("market_cap"), b.get("pos_52w"),
             1 if b.get("in_universe") else 0, json.dumps(b.get("universe_groups") or [], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return enriched


def _followed(only: list[str] | None = None) -> list[dict]:
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT hs_code, item_name, group_label FROM trade_follow WHERE active=1 ORDER BY group_label, hs_code").fetchall()]
    conn.close()
    return [r for r in rows if not only or r["hs_code"] in only]


def _windows(strt: str, end: str) -> list[tuple[str, str]]:
    """조회기간을 캘린더 연 단위(≤12개월)로 분할 — 관세청 API 1년 제한 대응."""
    sy, sm = int(strt[:4]), int(strt[4:6])
    ey, em = int(end[:4]), int(end[4:6])
    out = []
    for y in range(sy, ey + 1):
        out.append((f"{y}{(sm if y == sy else 1):02d}", f"{y}{(em if y == ey else 12):02d}"))
    return out


def collect_followed(only: list[str] | None = None, strt_yymm: str = "202401",
                     end_yymm: str | None = None) -> dict:
    """팔로우 품목의 월별 수출입 통계 수집 → trade_stats (멱등 upsert). 기간은 연 단위로 분할 호출."""
    from datetime import date
    if end_yymm is None:
        t = date.today()
        end_yymm = f"{t.year}{t.month:02d}"
    windows = _windows(strt_yymm, end_yymm)
    stored, failed = 0, 0
    for f in _followed(only):
        rows = []
        try:
            for ws, we in windows:
                rows += fetch(f["hs_code"], ws, we)
        except Exception as e:  # noqa: BLE001
            print(f"[trade] {f['hs_code']} {f['item_name']} 실패: {e}")
            failed += 1
            continue
        conn = get_connection()
        for row in rows:
            conn.execute(
                "INSERT INTO trade_stats (hs_code, period, export_usd, import_usd, export_wt, import_wt, balance_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hs_code, period) DO UPDATE SET "
                "export_usd=excluded.export_usd, import_usd=excluded.import_usd, export_wt=excluded.export_wt, "
                "import_wt=excluded.import_wt, balance_usd=excluded.balance_usd, fetched_at=datetime('now')",
                (f["hs_code"], row["period"], row["export_usd"], row["import_usd"],
                 row["export_wt"], row["import_wt"], row["balance_usd"]))
            stored += 1
        conn.commit()
        conn.close()
    return {"stored_rows": stored, "failed": failed, "items": len(_followed(only))}
