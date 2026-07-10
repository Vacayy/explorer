"""유·무상증자 상세 추출 (Pro 뷰) — 결정 공시 원문 → 구조화 필드.

- 대상: corporate_actions 중 유상증자/무상증자 '결정' 공시
- 추출: haiku 구조화 JSON (증자방식에 따라 필드 유무 다름 — 전부 nullable)
- 파생: 권리락 = 신주배정기준일 - 1거래일 (주말 보정; 공휴일은 근사)
- 정정 공시: 같은 종목의 최신 결정 공시가 이전 것을 대체 (rcp_no별 저장, 뷰에서 최신만)
"""
import json
from datetime import date, timedelta

from database import get_connection
from pipeline.actions import _fetch_document_text
from pipeline.enrich import _call_claude_code, llm_engine

FIELDS = """{
 "method": "주주배정|제3자배정|일반공모|무상 중 하나",
 "price_1st": 1차발행가(원, 정수) 또는 null,
 "price_2nd": null, "price_final": 확정발행가 또는 null,
 "old_shares": 증자전 발행주식총수 또는 null, "new_shares": 신주 수 또는 null,
 "date_price_1st": "1차발행가 산정일 YYYY-MM-DD" 또는 null,
 "date_record": "신주배정기준일" 또는 null,
 "date_rights_listing_start": "신주인수권증서 상장/매매 시작일" 또는 null,
 "date_rights_listing_end": null,
 "date_price_fix": "발행가 확정(예정)일" 또는 null,
 "date_sub_start": "구주주 청약 시작일" 또는 null, "date_sub_end": null,
 "date_public_start": "일반공모 청약 시작일" 또는 null, "date_public_end": null,
 "date_payment": "납입일" 또는 null,
 "date_new_listing": "신주 상장 예정일" 또는 null,
 "underwriter": "대표주관회사(들)" 또는 null,
 "major_holder": "최대주주 지분율 또는 청약 참여 관련 기재" 또는 null
}"""


def _prev_business_day(iso: str) -> str | None:
    """기준일 전 거래일 (주말 보정 — 공휴일은 근사)."""
    try:
        d = date.fromisoformat(iso) - timedelta(days=1)
    except ValueError:
        return None
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def _extract_one(rcp_no: str, corp_name: str, report_nm: str) -> dict | None:
    text = _fetch_document_text(rcp_no)
    if not text:
        return None
    prompt = (
        f"다음은 {corp_name}의 '{report_nm}' 공시 원문이다. JSON만 출력해라 (설명 금지).\n"
        f"형식:\n{FIELDS}\n"
        "규칙: 날짜는 YYYY-MM-DD로 정규화. 없는 항목은 null. 숫자는 콤마 없이 정수. "
        "발행가는 반드시 '신주 발행가액(1주당)' — 액면가·전환가·기준주가를 쓰지 마라. "
        "'~부터 ~까지' 기간은 start/end로 분리. 무상증자면 method='무상'.\n\n" + text
    )
    raw = _call_claude_code(prompt)
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])


def extract_pending(limit: int = 15) -> dict:
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}

    conn = get_connection()
    todo = conn.execute("""
        SELECT ca.rcp_no, ca.stock_code, ca.corp_name, ca.action_type, ca.report_nm, ca.rcept_dt
        FROM corporate_actions ca
        WHERE ca.action_type IN ('유상증자', '무상증자')
          AND ca.report_nm LIKE '%결정%'
          -- 종속/자회사 증자는 본체 주식 발행이 아님 → Pro 뷰 제외 (목록 뷰엔 유지)
          AND ca.report_nm NOT LIKE '%종속회사%'
          AND ca.report_nm NOT LIKE '%자회사%'
          AND ca.rcp_no NOT IN (SELECT rcp_no FROM capital_raise_details)
        ORDER BY ca.rcept_dt DESC LIMIT ?
    """, (limit,)).fetchall()

    done = failed = 0
    for r in todo:
        try:
            d = _extract_one(r["rcp_no"], r["corp_name"], r["report_nm"]) or {}
        except Exception:
            failed += 1
            continue
        rd = d.get("date_record")
        conn.execute("""
            INSERT OR IGNORE INTO capital_raise_details
                (rcp_no, stock_code, corp_name, action_type, method,
                 price_1st, price_2nd, price_final, old_shares, new_shares,
                 date_disclosure, date_price_1st, date_record, date_ex_rights,
                 date_rights_listing_start, date_rights_listing_end, date_price_fix,
                 date_sub_start, date_sub_end, date_public_start, date_public_end,
                 date_payment, date_new_listing, underwriter, major_holder)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (r["rcp_no"], r["stock_code"], r["corp_name"], r["action_type"], d.get("method"),
              d.get("price_1st"), d.get("price_2nd"), d.get("price_final"),
              d.get("old_shares"), d.get("new_shares"),
              f"{r['rcept_dt'][:4]}-{r['rcept_dt'][4:6]}-{r['rcept_dt'][6:]}",
              d.get("date_price_1st"), rd, _prev_business_day(rd) if rd else None,
              d.get("date_rights_listing_start"), d.get("date_rights_listing_end"),
              d.get("date_price_fix"), d.get("date_sub_start"), d.get("date_sub_end"),
              d.get("date_public_start"), d.get("date_public_end"),
              d.get("date_payment"), d.get("date_new_listing"),
              d.get("underwriter"), d.get("major_holder")))
        conn.commit()
        done += 1

    conn.close()
    return {"extracted": done, "failed": failed, "checked": len(todo)}
