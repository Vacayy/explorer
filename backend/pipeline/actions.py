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


def _fetch_document_text(rcp_no: str) -> str | None:
    """DART 공시 원문 → 텍스트 (앞 4000자 — 요약에 충분)."""
    import re as _re
    import warnings

    import OpenDartReader
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    try:
        dart = OpenDartReader(DART_API_KEY)
        doc = dart.document(rcp_no)
        if not doc:
            return None
        text = BeautifulSoup(doc, "html.parser").get_text("\n")
        return _re.sub(r"\n{2,}", "\n", text).strip()[:4000]
    except Exception:
        return None


def summarize_pending(limit: int = 20) -> dict:
    """summary 없는 기업활동 공시를 haiku로 요약 (규모·비율·일정·목적 중심)."""
    from pipeline.enrich import _call_claude_code, llm_engine

    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}

    conn = get_connection()
    todo = conn.execute("""
        SELECT id, rcp_no, corp_name, action_type, report_nm FROM corporate_actions
        WHERE summary IS NULL ORDER BY rcept_dt DESC LIMIT ?
    """, (limit,)).fetchall()

    done = failed = 0
    for r in todo:
        text = _fetch_document_text(r["rcp_no"])
        if not text:
            conn.execute("UPDATE corporate_actions SET summary='(원문 조회 실패)' WHERE id=?", (r["id"],))
            conn.commit()
            failed += 1
            continue
        prompt = (
            f"다음은 {r['corp_name']}의 '{r['report_nm']}' 공시 원문이다. "
            "투자자 관점 핵심만 2~3문장으로 요약해라 (규모/비율/신주 수·발행가/기준일·일정/목적). "
            "수치를 우선하고 군더더기 금지. 텍스트만 출력.\n\n" + text
        )
        try:
            summary = _call_claude_code(prompt).strip()[:600]
            conn.execute("UPDATE corporate_actions SET summary=? WHERE id=?", (summary, r["id"]))
            conn.commit()
            done += 1
        except Exception:
            failed += 1

    conn.close()
    return {"summarized": done, "failed": failed, "remaining_checked": len(todo)}


# ---------- 목록 한 줄 설명 (LLM 0 — 저장된 값만) ----------

DESCRIPTION_MAX = 120


def _first_sentence(text: str) -> str:
    import re
    flat = re.sub(r"\s+", " ", text).strip()
    m = re.search(r"(?<=[가-힣a-zA-Z)\]%])\.(?=\s|$)", flat)
    return flat[: m.end()] if m else flat


def _clip(text: str, limit: int = DESCRIPTION_MAX) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(" ,·") + "…"


def _raise_line(d) -> str | None:
    """유·무상증자 추출 상세(capital_raise_details) → '제3자배정 · 확정 발행가 204,500원 · 신주 6,558,435주(기존 대비 4.3%)'."""
    parts = []
    if d["method"]:
        parts.append(d["method"])
    for key, label in (("price_final", "확정"), ("price_2nd", "2차"), ("price_1st", "1차")):
        if d[key]:
            parts.append(f"{label} 발행가 {d[key]:,}원")
            break
    if d["new_shares"]:
        ratio = f"(기존 대비 {d['new_shares'] / d['old_shares'] * 100:.1f}%)" if d["old_shares"] else ""
        parts.append(f"신주 {d['new_shares']:,}주{ratio}")
    return " · ".join(parts) if len(parts) > 1 else None


def action_description(report_nm: str | None, summary: str | None, detail=None) -> str | None:
    """기업활동 목록 제목 아래 한 줄 — 하나씩 열어 보지 않아도 무엇인지 알게(D-306 5).

    우선순위: 증자 추출 상세(구조화 값) → 저장된 요약의 첫 문장 → 자회사 공시 표시 → 없음.
    요약은 스캔 때 이미 만든 것만 쓴다(여기서 새로 만들지 않는다). '(원문 조회 실패)'는 설명으로 쓰지 않는다.
    """
    if detail is not None:
        line = _raise_line(detail)
        if line:
            return line
    s = (summary or "").strip()
    if s and not s.startswith("("):
        return _clip(_first_sentence(s))
    name = report_nm or ""
    if "종속회사" in name or "자회사" in name:
        return "자회사 관련 공시입니다."
    return None
