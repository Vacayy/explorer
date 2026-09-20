"""DART 정기보고서 'II. 사업의 내용' 본문 확보 (docs/specs/company-research.md §웹 조사 레인, D-188 후속).

OpenDART 목록 API로 최신 정기보고서(사업·반기·분기)를 찾고, 하위 문서 URL(sub_docs)에서 사업의 개요·주요 제품·매출 절의
HTML을 받아 텍스트로 만든다. 모델 호출은 없다. 결과는 raw_documents(source_type='dart_business')에 보고서 단위로 한 번 저장한다.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Callable

SECTION_PATTERNS = (
    ("overview", r"^\s*1\.\s*사업의\s*개요"),
    ("products", r"^\s*2\.\s*주요\s*제품"),
    ("materials", r"^\s*3\.\s*원재료"),
    ("sales", r"^\s*4\.\s*매출\s*및\s*수주"),
    ("contracts", r"^\s*6\.\s*주요\s*계약"),
    ("other", r"^\s*7\.\s*기타\s*참고"),
)
SECTION_LIMIT = 9000
TOTAL_LIMIT = 30000
PERIODIC = re.compile(r"(사업|반기|분기)보고서")


class DartBusinessUnavailable(RuntimeError):
    """DART 목록·본문을 받지 못한 상태. 호출자는 gaps에 사유를 남긴다."""


def _text(html: str) -> str:
    from bs4 import BeautifulSoup
    text = BeautifulSoup(html or "", "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def viewer_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def latest_periodic_report(dart, corp_code: str, today: date | None = None) -> dict | None:
    """최근 400일 안의 가장 최신 정기보고서. 없으면 None."""
    today = today or date.today()
    frame = dart.list(corp_code, start=(today - timedelta(days=400)).isoformat(), end=today.isoformat(), kind="A")
    if frame is None or len(frame) == 0:
        return None
    for _, row in frame.iterrows():
        name = str(row.get("report_nm") or "")
        if PERIODIC.search(name):
            stamp = str(row.get("rcept_dt") or "")
            return {"rcept_no": str(row["rcept_no"]), "report_nm": name,
                    "rcept_dt": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}" if re.fullmatch(r"\d{8}", stamp) else None}
    return None


def fetch_sections(dart, rcept_no: str, fetch: Callable[[str], str]) -> list[dict]:
    """사업의 내용 하위 절을 텍스트로. 절 순서를 유지하고 총량을 제한한다."""
    frame = dart.sub_docs(rcept_no)
    sections, total = [], 0
    for _, row in frame.iterrows():
        title = str(row.get("title") or "")
        key = next((k for k, pattern in SECTION_PATTERNS if re.match(pattern, title)), None)
        if key is None or total >= TOTAL_LIMIT:
            continue
        text = _text(fetch(str(row["url"])))[:SECTION_LIMIT]
        if len(text) < 40:
            continue
        sections.append({"key": key, "title": re.sub(r"\s+", " ", title).strip(), "text": text, "url": str(row["url"])})
        total += len(text)
    return sections


def default_fetch(url: str) -> str:
    import requests
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Explorer research)"})
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def stored_sections(conn: sqlite3.Connection, code: str) -> dict | None:
    rows = conn.execute("SELECT source_id, title, url, published_at, markdown FROM raw_documents WHERE source_type='dart_business' "
                        "AND source_id LIKE ? ORDER BY published_at DESC, id", (f"{code}:%",)).fetchall()
    if not rows:
        return None
    rcept_no = rows[0]["source_id"].split(":")[1]
    latest = [r for r in rows if r["source_id"].split(":")[1] == rcept_no]
    report_nm = latest[0]["title"].split(" · ")[0]
    return {"rcept_no": rcept_no, "report_nm": report_nm, "rcept_dt": latest[0]["published_at"], "url": viewer_url(rcept_no),
            "sections": [{"key": r["source_id"].split(":")[2], "title": r["title"].split(" · ", 1)[-1], "text": r["markdown"], "url": r["url"]} for r in latest]}


def ensure_business_text(conn: sqlite3.Connection, code: str, corp_code: str, name: str, *, dart=None,
                         fetch: Callable[[str], str] | None = None, today: date | None = None) -> dict:
    """최신 정기보고서의 사업의 내용을 확보한다. 같은 보고서가 이미 저장돼 있으면 재사용."""
    if dart is None:
        from config import DART_API_KEY
        if not DART_API_KEY:
            raise DartBusinessUnavailable("DART 인증 설정이 없습니다.")
        from services.dart_service import _get_dart
        dart = _get_dart()
    try:
        report = latest_periodic_report(dart, corp_code, today)
    except Exception as exc:
        raise DartBusinessUnavailable(f"DART 공시 목록 조회 실패: {str(exc)[:120]}") from exc
    if report is None:
        raise DartBusinessUnavailable("최근 400일 안의 정기보고서(사업·반기·분기)가 없습니다.")
    current = stored_sections(conn, code)
    if current and current["rcept_no"] == report["rcept_no"]:
        return current
    try:
        sections = fetch_sections(dart, report["rcept_no"], fetch or default_fetch)
    except Exception as exc:
        raise DartBusinessUnavailable(f"사업의 내용 본문 수신 실패: {str(exc)[:120]}") from exc
    if not sections:
        raise DartBusinessUnavailable("보고서에서 사업의 내용 절을 찾지 못했습니다.")
    import hashlib
    for section in sections:
        markdown = f"{name} · {report['report_nm']} · {section['title']}\n\n{section['text']}"
        conn.execute("INSERT OR IGNORE INTO raw_documents (source_type, source_id, title, url, published_at, raw_content, markdown, content_hash) "
                     "VALUES ('dart_business', ?, ?, ?, ?, ?, ?, ?)",
                     (f"{code}:{report['rcept_no']}:{section['key']}", f"{report['report_nm']} · {section['title']}", section["url"],
                      report["rcept_dt"], section["text"], markdown, hashlib.sha256(markdown.encode()).hexdigest()))
    conn.commit()
    return {**report, "url": viewer_url(report["rcept_no"]), "sections": sections}


def official_excerpt(business: dict, *, limit: int = 12000) -> str:
    """모델 프롬프트용 발췌: 개요 전체 → 주요 제품 → 매출 순으로 한도 안에서."""
    order = {"overview": 0, "products": 1, "sales": 2, "materials": 3, "contracts": 4, "other": 5}
    out, used = [], 0
    for section in sorted(business["sections"], key=lambda s: order.get(s["key"], 9)):
        room = limit - used
        if room <= 0:
            break
        text = section["text"][:room]
        out.append(f"[{section['title']}]\n{text}")
        used += len(text)
    return "\n\n".join(out)
