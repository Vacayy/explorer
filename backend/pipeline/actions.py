"""기업활동(Corporate Actions) 스캔 — DART 전 시장 공시 목록에서 분류.

- 대상: 시가총액 MIN_MARKET_CAP(기본 5,000억) 이상 KOSPI/KOSDAQ 상장사
- 분류: report_nm 키워드 (기재정정 포함 — 정정 이력도 보임)
- 멱등: rcp_no UNIQUE. cron 30분 체인에서 최근 며칠 재스캔해도 안전.
- 참고: 권리락은 DART 공시가 아니라 KRX 시장조치 — 유·무상증자 공시의
  신주배정기준일에서 파생되므로 v1 범위 밖 (공시 원문에서 확인 가능).
"""
import requests

from config import DART_API_KEY
from database import get_connection

MIN_MARKET_CAP = 500_000_000_000  # 5,000억

# 순서 중요 — 먼저 매칭되는 타입이 승리 ('분할합병'은 합병보다 주식분할 아님 등)
ACTION_RULES = [
    ("주식분할", ["주식분할", "액면분할"]),
    ("무상증자", ["무상증자"]),
    ("유상증자", ["유상증자"]),
    ("공개매수", ["공개매수"]),
    ("감자", ["감자"]),
    ("합병", ["합병"]),          # 분할합병 포함
    ("회사분할", ["분할"]),       # 남은 '분할' = 회사분할
]


def _classify(report_nm: str) -> str | None:
    for action, kws in ACTION_RULES:
        if any(k in report_nm for k in kws):
            return action
    return None


def _latest_marcap(conn) -> dict[str, int]:
    rows = conn.execute("""
        SELECT stock_code, market_cap FROM stock_prices
        WHERE (stock_code, trade_date) IN (
            SELECT stock_code, max(trade_date) FROM stock_prices
            WHERE market_cap IS NOT NULL GROUP BY stock_code)
    """).fetchall()
    return {r["stock_code"]: r["market_cap"] for r in rows if r["market_cap"]}


def scan(bgn_de: str, end_de: str, min_market_cap: int = MIN_MARKET_CAP) -> dict:
    """DART 목록 API 페이지 순회 → 분류·시총 필터 → corporate_actions upsert."""
    conn = get_connection()
    marcap = _latest_marcap(conn)
    stats = {"scanned": 0, "matched": 0, "inserted": 0}

    page = 1
    while True:
        resp = requests.get("https://opendart.fss.or.kr/api/list.json", params={
            "crtfc_key": DART_API_KEY, "bgn_de": bgn_de, "end_de": end_de,
            "page_no": page, "page_count": 100}, timeout=30)
        data = resp.json()
        if data.get("status") != "000":
            break
        for item in data.get("list", []):
            stats["scanned"] += 1
            if item.get("corp_cls") not in ("Y", "K"):
                continue
            action = _classify(item.get("report_nm", ""))
            if not action:
                continue
            code = (item.get("stock_code") or "").strip()
            cap = marcap.get(code)
            if not cap or cap < min_market_cap:
                continue
            stats["matched"] += 1
            cur = conn.execute("""
                INSERT OR IGNORE INTO corporate_actions
                    (rcp_no, corp_code, corp_name, stock_code, market, action_type,
                     report_nm, rcept_dt, market_cap)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item["rcept_no"], item.get("corp_code"), item.get("corp_name"),
                  code, item.get("corp_cls"), action, item.get("report_nm"),
                  item.get("rcept_dt"), cap))
            stats["inserted"] += cur.rowcount
        conn.commit()
        if page >= int(data.get("total_page", 1)):
            break
        page += 1

    conn.close()
    return stats
