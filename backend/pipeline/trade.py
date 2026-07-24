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

BASE = "http://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

# 기본 팔로우 시드 (2026-07-24 리서치) — HS부호·품목명. 관련 종목은 런타임 LLM 지목.
# 플래그십은 4단위(정밀), 광범위 카테고리는 2단위(전체 포괄).
DEFAULT_FOLLOWS = [
    ("8542", "반도체(집적회로)", "IT"),
    ("8541", "반도체(개별소자·전력)", "IT"),
    ("8517", "무선통신기기", "IT"),
    ("8471", "컴퓨터", "IT"),
    ("8524", "디스플레이(평판모듈)", "IT"),
    ("8703", "승용자동차", "자동차"),
    ("8708", "자동차부품", "자동차"),
    ("8507", "2차전지(축전지)", "2차전지"),
    ("2710", "석유제품", "에너지"),
    ("39", "플라스틱·합성수지", "소재"),
    ("72", "철강", "소재"),
    ("89", "선박", "기계"),
]

# 응답 필드 후보 (관세청 표준 + 변형 대비) — 첫 확정 후 정리
_F = {
    "period": ("year", "statYymm", "yymm"),
    "export_usd": ("expDlr", "expUsd"),
    "import_usd": ("impDlr", "impUsd"),
    "export_wt": ("expWgt",),
    "import_wt": ("impWgt",),
    "hs": ("hsCd", "hsSgn"),
    "name": ("statKor", "korPrlmNm"),
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
    """관세청 품목별 수출입실적 조회 → 월별 정규화 dict 리스트. raw 보존."""
    if not DATA_GO_KR_KEY:
        raise RuntimeError("DATA_GO_KR_KEY 미설정 — .env에 공공데이터포털 서비스키 필요")
    r = requests.get(BASE, params={
        "serviceKey": DATA_GO_KR_KEY, "strtYymm": strt_yymm, "endYymm": end_yymm, "hsSgn": hs_code},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = []
    for item in root.iter("item"):
        period = _norm_period(_pick(item, _F["period"]))
        if not period:
            continue
        exp = _num(_pick(item, _F["export_usd"]))
        imp = _num(_pick(item, _F["import_usd"]))
        out.append({
            "period": period,
            "export_usd": exp, "import_usd": imp,
            "export_wt": _num(_pick(item, _F["export_wt"])),
            "import_wt": _num(_pick(item, _F["import_wt"])),
            "balance_usd": (exp - imp) if (exp is not None and imp is not None) else None,
            "name": _pick(item, _F["name"]),
        })
    return out


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


def _followed(only: list[str] | None = None) -> list[dict]:
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT hs_code, item_name, group_label FROM trade_follow WHERE active=1 ORDER BY group_label, hs_code").fetchall()]
    conn.close()
    return [r for r in rows if not only or r["hs_code"] in only]


def collect_followed(only: list[str] | None = None, strt_yymm: str = "202401",
                     end_yymm: str | None = None) -> dict:
    """팔로우 품목의 월별 수출입 통계 수집 → trade_stats (멱등 upsert)."""
    from datetime import date
    if end_yymm is None:
        t = date.today()
        end_yymm = f"{t.year}{t.month:02d}"
    stored, failed = 0, 0
    for f in _followed(only):
        try:
            rows = fetch(f["hs_code"], strt_yymm, end_yymm)
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
