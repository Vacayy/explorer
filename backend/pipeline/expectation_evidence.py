"""Isolated, read-only inspection of existing corpus. No LLM, lazy generation or writes."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import sqlite3

from config import DB_PATH
from models.expectations import AttributionCue, EvidenceDocument, EvidencePage

PRODUCTS = {
    "hbm": re.compile(r"\bHBM\w*|고대역폭\s*메모리", re.I),
    "dram": re.compile(r"\b(?:DRAM|DDR[3456]?|LPDDR\w*|GDDR\w*)\b|디램|D램", re.I),
    "nand": re.compile(r"\b(?:NAND|SSD|QLC|TLC)\b|낸드", re.I),
}
SUPPORTED = ("blog", "telegram", "youtube")
# These locate text for review, never establish identity or endorsement.
CUES = {
    "self_introduction": re.compile(r"안녕하세요[.。!\s]*[^\n.!?]{1,50}입니다[.!?]?"),
    "signature": re.compile(r"^\s*[-—]\s*[^\n]{1,70}$", re.M),
    "reported_speech": re.compile(r"(?:\([^\n)]{1,70}\)|\[[^\n\]]{1,70}\]|[^\n]{0,35}(?:인터뷰|인용|자료:|리포트)[^\n]{0,65})"),
}


@contextmanager
def evidence_connection():
    # Do not use database.get_connection: this route must not set WAL or initialize schema.
    conn = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


def inspect_document(row, *, include_text=False):
    raw = row["raw_content"] or ""
    markdown = row["markdown"] or ""
    # A known generated representation disqualifies the document until representations
    # can be separated. Missing marker never proves original authorship.
    derived = row["source_type"] == "youtube" and row["digest_status"] == "ok"
    derived = derived or any("원본 자막" in t and "정리본" in t for t in (raw, markdown))
    field = "markdown" if markdown.strip() else "raw_content"
    text = markdown if field == "markdown" else raw
    kind = "derived_summary" if derived else (
        "empty" if not text.strip() else (
            "stored_transcript" if row["source_type"] == "youtube" else "stored_text"))
    warnings = ["저장본의 출처·실제 화자·주장 정확성은 아직 검증하지 않았습니다."]
    if derived:
        warnings.append("AI 정리본입니다. 직접 발언의 원문 인용이나 화자 판정에 사용하지 마세요.")
    if kind == "stored_transcript":
        warnings.append("저장 자막 후보입니다. 음성인식 오류·화자 구분·타임코드는 확인되지 않았습니다.")
    if kind == "empty":
        warnings.append("저장 텍스트가 없습니다. 첨부 자료는 이 API에서 해석하지 않습니다.")
    if field == "raw_content" and re.search(r"<(?:div|p|html)\b", text, re.I):
        warnings.append("HTML 저장본입니다. 평문 정규화와 원문 구간 대응 검토가 필요합니다.")
    if not row["published_at"]:
        warnings.append("발표 시각 미상입니다. 수집 시각으로 대체하지 않았습니다.")
    cues = []
    if kind in ("stored_text", "stored_transcript"):
        for cue_kind, pattern in CUES.items():
            for match in pattern.finditer(text):
                cues.append(AttributionCue(kind=cue_kind, text=match.group(),
                                           start=match.start(), end=match.end()))
                if len(cues) >= 12:
                    break
            if len(cues) >= 12:
                break
    products = [key for key, pattern in PRODUCTS.items() if pattern.search((row["title"] or "") + "\n" + text)]
    return EvidenceDocument(
        id=row["id"], source_type=row["source_type"], source_id=row["source_id"],
        source_url=row["url"], title=row["title"], published_at=row["published_at"],
        fetched_at=row["fetched_at"], products=products, text_kind=kind,
        text_field=field, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text_length=len(text), text=text if include_text else None,
        source_text_available=kind in ("stored_text", "stored_transcript"),
        attribution_cues=cues, warnings=warnings)


def get_document(doc_id):
    with evidence_connection() as conn:
        row = conn.execute("SELECT * FROM raw_documents WHERE id=?", (doc_id,)).fetchone()
        if row is None or row["source_type"] not in SUPPORTED:
            return None
        return inspect_document(row, include_text=True)


def list_documents(*, before_id=None, source_type=None, product=None, limit=20):
    clauses = ["source_type IN ('blog','telegram','youtube')"]
    params = []
    if before_id is not None:
        clauses.append("id < ?")
        params.append(before_id)
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    # Bound work per request. Cursor advances over scanned records, including nonmatches.
    with evidence_connection() as conn:
        rows = conn.execute("SELECT * FROM raw_documents WHERE " + " AND ".join(clauses)
                            + " ORDER BY id DESC LIMIT 501", params).fetchall()
    items, scanned, last_id = [], 0, None
    for row in rows[:500]:
        scanned += 1
        last_id = row["id"]
        doc = inspect_document(row)
        if doc.products and (not product or product in doc.products):
            items.append(doc)
        if len(items) >= limit:
            break
    more = len(rows) > scanned
    return EvidencePage(items=items, scanned=scanned, has_more=more,
                        next_before_id=last_id if more else None)
