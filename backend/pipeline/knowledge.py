"""사용자 지식 주입 — knowledge-system.md ①.

"삼성전자는 최근 노조와 성과급 이슈로 골머리를 앓았다" 같은 지식을
대화·옴니바·봇에서 바로 온톨로지에 넣는 입구.

원칙:
- 소유권 분할 유지: vault/notes/*.md 가 원본, DB는 파생 인덱스.
  NoteConnector와 같은 source_id 규약 → 이후 주기 수집에서 중복 없이 관리.
- garbage 방어는 입구 검열이 아니라 provenance: epistemic(사실|가설)을
  본문 관례(> 가설: …)로 명시, 소비 지점(RAG·피드)은 note를 구분 취급.
- 태깅·링크는 기존 파이프라인(store_document → enrich → _link) 그대로.
"""
import re
from datetime import datetime, timezone

from config import VAULT_PATH
from pipeline.base import RawDoc
from pipeline.store import store_document
from database import get_connection

EPISTEMIC_LABEL = {"fact": "사실", "hypothesis": "가설"}


def _slug(text: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", text.strip())[:40].strip("-")
    return s or "지식"


def inject_knowledge(content: str, epistemic: str = "hypothesis") -> dict:
    """지식 한 조각 → vault 노트 생성 + 즉시 흡수. 반환: {doc_id, title, entities}."""
    content = (content or "").strip()
    if not content:
        raise ValueError("내용이 비어 있습니다")
    if epistemic not in EPISTEMIC_LABEL:
        epistemic = "hypothesis"

    now = datetime.now(timezone.utc)
    title = content.splitlines()[0].strip()[:60]
    label = EPISTEMIC_LABEL[epistemic]

    notes_dir = VAULT_PATH / "notes" / "injected"
    notes_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}.md"
    path = notes_dir / fname
    md = (
        f"# {title}\n\n"
        f"> {label} (사용자 주입 · {now.strftime('%Y-%m-%d')})\n\n"
        f"{content}\n"
    )
    path.write_text(md, encoding="utf-8")

    # NoteConnector.fetch와 동일 규약으로 즉시 흡수 (다음 주기 수집과 멱등)
    doc = RawDoc(
        source_type="note",
        source_id=str(path.relative_to(VAULT_PATH / "notes")),
        title=title,
        url="",
        published_at=now.isoformat(),
        raw_content=md,
        kind="text",
    )
    store_document(doc)

    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM raw_documents WHERE source_type='note' AND source_id=?",
        (doc.source_id,)).fetchone()
    entities = []
    if row:
        entities = [r["name"] for r in conn.execute("""
            SELECT DISTINCT e.name FROM entity_links el JOIN entities e ON el.entity_id=e.id
            WHERE el.doc_id=? ORDER BY el.confidence DESC LIMIT 6""", (row["id"],))]
    conn.close()
    return {"doc_id": row["id"] if row else None, "title": title,
            "epistemic": epistemic, "entities": entities}


REMEMBER_PREFIXES = ("기억해(사실):", "기억해(사실)", "기억해:", "기억해 ", "메모:")


def parse_remember(text: str) -> tuple[str, str] | None:
    """'기억해: …' 류 명령 파싱 → (내용, epistemic) 또는 None."""
    q = (text or "").strip()
    for prefix in REMEMBER_PREFIXES:
        if q.startswith(prefix):
            content = q[len(prefix):].strip()
            if not content:
                return None
            epistemic = "fact" if "(사실)" in prefix else "hypothesis"
            return content, epistemic
    return None
