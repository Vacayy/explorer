"""국내 잠정실적 공시 숫자 추출 — Sankey '분기 손익 흐름'의 1단계 fallback (ia-redesign §4.13).

흐름:
1. `disclosures`에서 '매출액또는손익구조30%(대규모법인은15%)이상변경' 공시(한 corp의 최근 N건)를 대상으로 선택.
2. DART 뷰어 HTML(`/report/viewer.do?rcpNo=…&dcmNo=…`)을 받아 LLM(haiku, task='preliminary.extract')에 통째 넘겨
   {period, fs_div, revenue, op_income, net_income}을 JSON으로 받는다.
3. 성공하면 `kr_preliminary_earnings`에 upsert.

LLM 선택 이유: 공시 HTML 표 구조가 회사마다 다르고(연간·분기·이번 분기만/누적 혼재) 포맷이 수차례 바뀌어
규칙형 파서로 커버리지를 확보하기 어렵다. 숫자 3개만 꺼내는 단일 질문이라 비용은 분당 공시당 ~$0.0002 수준이다.

`financial_statements`에 같은 분기가 들어오면(분기보고서 공시) 자동으로 Sankey가 2단계(세부 노드 포함)로
바뀌므로 잠정 숫자는 자연스레 가려진다. 이 수집기는 분기보고서 전 공백만 메운다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

import requests

from database import get_connection
from pipeline import llm

VIEWER_URL = "https://dart.fss.or.kr/report/viewer.do"
MAIN_URL = "https://dart.fss.or.kr/dsaf001/main.do"
UA = {"User-Agent": "Mozilla/5.0 (compatible; explorer/1.0)"}
REPRT_MONTH = {"11013": "03", "11012": "06", "11014": "09", "11011": "12"}
MONTH_TO_Q = {"03": 1, "06": 2, "09": 3, "12": 4}


SYSTEM_PROMPT = """이 HTML은 DART '매출액 또는 손익구조 30%(대규모법인 15%)이상 변경' 공시 본문이다.
표에서 **당해 결산기간**(이번 공시가 발표한 기간)의 매출액·영업이익(또는 영업손익)·당기순이익 세 값을 꺼내라.
단위는 원(KRW)으로 환산해 **정수**로 돌려준다 — 공시가 '백만원' 단위면 ×1,000,000, '천원'이면 ×1,000.
음수는 그대로 음수 정수. 모르면 null.

period는 결산기간의 **끝나는 월**을 'YY.MM'으로 (예: 2026-06-30이면 '26.06'). 사업연도 끝(12-31)이면 'YY.12'.
fs_div는 '연결'/'별도' 중 하나(공시가 밝힌 '재무제표의 종류')를 영문으로: 연결=CFS, 별도=OFS.

반환 JSON만:
{"period": "YY.MM", "fs_div": "CFS"|"OFS"|null, "revenue": int|null, "op_income": int|null, "net_income": int|null}

표 안의 '%(비교)' 열이나 '직전사업연도' 열의 값은 쓰지 않는다. 당해 결산기간 값만 꺼낸다."""


PRELIM_REPORT_NM = (
    "매출액또는손익구조30%(대규모법인은15%)이상변경",
    "매출액또는손익구조30%(대규모법인은15%)이상변경(자회사의주요경영사항)",
    "매출액 또는 손익구조 30%(대규모법인은 15%)이상 변경",
)


def _fetch_doc_html(rcp_no: str) -> str | None:
    """main.do → viewDoc(…) 인자 추출 → viewer.do HTML. 한 번이라도 네트워크 오류면 None."""
    try:
        r = requests.get(MAIN_URL, params={"rcpNo": rcp_no}, headers=UA, timeout=15)
        r.raise_for_status()
    except Exception:
        return None
    m = re.search(r"viewDoc\(\s*\"(\d+)\"\s*,\s*\"(\d+)\"\s*,\s*\"(\d+)\"\s*,\s*\"(\d+)\"\s*,\s*\"(\d+)\"\s*,\s*\"([^\"]+)\"", r.text)
    if not m:
        return None
    rcp, dcm, ele, offset, length, dtd = m.groups()
    try:
        v = requests.get(VIEWER_URL, params={
            "rcpNo": rcp, "dcmNo": dcm, "eleId": ele,
            "offset": offset, "length": length, "dtd": dtd,
        }, headers=UA, timeout=15)
        v.raise_for_status()
    except Exception:
        return None
    return v.text


def _parse_llm_json(payload: str) -> dict | None:
    """LLM 결과에서 첫 JSON 객체를 뽑는다. 코드펜스·앞뒤 설명을 허용."""
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", payload, re.DOTALL):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["period", "fs_div", "revenue", "op_income", "net_income"],
    "properties": {
        "period": {"type": ["string", "null"], "pattern": r"^\d{2}\.(03|06|09|12)$"},
        "fs_div": {"type": ["string", "null"], "enum": ["CFS", "OFS", None]},
        "revenue": {"type": ["number", "null"]},
        "op_income": {"type": ["number", "null"]},
        "net_income": {"type": ["number", "null"]},
    },
}


def extract_one(stock_code: str, rcp_no: str, rcept_dt: str | None) -> dict | None:
    """공시 하나 처리 — HTML 받아 LLM로 숫자 추출 후 upsert. 실패는 None."""
    html = _fetch_doc_html(rcp_no)
    if not html:
        return {"status": "fetch_failed", "rcp_no": rcp_no}
    # 공시 본문이 크지 않다(≤20KB 수준). 통째로 넘긴다
    prompt = (f"공시 HTML:\n\n{html[:30000]}\n\n"
              f"위 규칙대로 숫자 3개를 JSON으로.")
    try:
        result = llm.run(prompt, task="preliminary.extract", system=SYSTEM_PROMPT, json_schema=SCHEMA)
    except Exception as e:  # noqa: BLE001
        return {"status": "llm_error", "rcp_no": rcp_no, "error": type(e).__name__}
    parsed = _parse_llm_json(result.text)
    if not parsed or not parsed.get("period"):
        return {"status": "parse_failed", "rcp_no": rcp_no, "raw": result.text[:200]}
    _store(stock_code, parsed, rcp_no, rcept_dt)
    return {"status": "ok", "rcp_no": rcp_no, **parsed}


def _store(stock_code: str, parsed: dict, rcp_no: str, rcept_dt: str | None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO kr_preliminary_earnings "
            "(stock_code, period, fs_div, revenue, op_income, net_income, rcp_no, rcept_dt, source_url, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?, datetime('now')) "
            "ON CONFLICT(stock_code, period) DO UPDATE SET "
            "fs_div=excluded.fs_div, revenue=excluded.revenue, op_income=excluded.op_income, "
            "net_income=excluded.net_income, rcp_no=excluded.rcp_no, rcept_dt=excluded.rcept_dt, "
            "source_url=excluded.source_url, fetched_at=excluded.fetched_at",
            (stock_code, parsed["period"], parsed.get("fs_div"), parsed.get("revenue"),
             parsed.get("op_income"), parsed.get("net_income"),
             rcp_no, rcept_dt, f"{MAIN_URL}?rcpNo={rcp_no}"),
        )
        conn.commit()
    finally:
        conn.close()


def _pending_disclosures(conn, limit: int | None) -> list[tuple[str, str, str, str]]:
    """아직 처리하지 않은(또는 최근 K건) 잠정공시 목록. 반환: (stock_code, rcp_no, report_nm, rcept_dt)."""
    names = ",".join("?" for _ in PRELIM_REPORT_NM)
    sql = f"""
        SELECT c.stock_code, d.rcp_no, d.report_nm, d.rcept_dt
        FROM disclosures d
        JOIN companies c ON c.corp_code = d.corp_code
        WHERE d.report_nm IN ({names}) AND c.stock_code IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM kr_preliminary_earnings p
            WHERE p.stock_code = c.stock_code AND p.rcp_no = d.rcp_no
          )
        ORDER BY d.rcept_dt DESC
    """
    rows = conn.execute(sql, PRELIM_REPORT_NM).fetchall()
    if limit is not None:
        rows = rows[:limit]
    return [(r["stock_code"], r["rcp_no"], r["report_nm"], r["rcept_dt"]) for r in rows]


def collect(limit: int | None = 30) -> dict:
    """미처리 잠정공시 최대 N건을 받아 추출·저장. 매일 아침 실적시즌만 돌리면 비용이 쌓이지 않는다."""
    conn = get_connection()
    try:
        pending = _pending_disclosures(conn, limit)
    finally:
        conn.close()
    stored, failed, parse_failed = 0, 0, 0
    first_errors: list[str] = []
    for stock_code, rcp_no, _report_nm, rcept_dt in pending:
        rcept = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}" if rcept_dt and len(rcept_dt) == 8 else rcept_dt
        r = extract_one(stock_code, rcp_no, rcept)
        if r is None:
            failed += 1
            continue
        if r.get("status") == "ok":
            stored += 1
        else:
            parse_failed += 1
            if len(first_errors) < 3:
                first_errors.append(f"{stock_code}/{rcp_no}: {r.get('status')}")
    return {"attempted": len(pending), "stored": stored, "parse_failed": parse_failed,
            "failed": failed, "errors": first_errors,
            "status": "ok" if stored else ("error" if not pending else "partial")}
