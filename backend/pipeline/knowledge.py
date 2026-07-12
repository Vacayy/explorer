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
        # K3: 사용자 지식도 knowledge 계층에 편입 — 기계 관측과 같은 수명주기
        register_user_knowledge(conn, row["id"], content, epistemic, now.isoformat())
    conn.close()
    return {"doc_id": row["id"] if row else None, "title": title,
            "epistemic": epistemic, "entities": entities}


def _classify_layer(statement: str) -> str:
    """pace layer 한 단어 판정 (haiku) — 실패 시 cycle."""
    from pipeline.enrich import llm_engine, _call_claude_code
    if llm_engine() != "claude-code":
        return "cycle"
    prompt = (
        "다음 투자 관련 주장의 시간 지평을 분류해라.\n"
        "- EVENT: 하루짜리 사건 (주가 등락, 단건 공시)\n"
        "- FLOW: 수주~수개월 흐름 (수급, 분기 실적 추세)\n"
        "- CYCLE: 1~수년 사이클 (업황, 공급부족)\n"
        "- STRUCTURE: 산업·기업의 구조 변화 (사업모델, 계약 구조)\n"
        "- REGIME: 정책·체제 (규제, 지정학)\n"
        "마지막 줄에 정확히 한 단어만.\n\n" + statement[:400]
    )
    try:
        hits = re.findall(r"\b(EVENT|FLOW|CYCLE|STRUCTURE|REGIME)\b", _call_claude_code(prompt))
        return hits[-1].lower() if hits else "cycle"
    except Exception:
        return "cycle"


def register_user_knowledge(conn, doc_id: int, content: str, epistemic: str, observed_at: str) -> int | None:
    """주입 지식 → knowledge 행 (K3). 시장 엔티티 링크가 없으면 건너뜀 (개인 메모).

    - 가설 → hypothesis, 사실 → observed. review_status='active' (내 지식은 승인 불필요)
    - 증거 1호 = 주입 노트 자신 (독립). 이후 K2 모순 스캔이 수집 문서로
      지지/반박을 붙이고, 독립 지지 2+면 corroborated — 기계가 내 가설을 확인.
    """
    market_ents = conn.execute("""
        SELECT DISTINCT el.entity_id FROM entity_links el JOIN entities e ON e.id = el.entity_id
        WHERE el.doc_id=? AND e.type IN ('company','sector','theme') """, (doc_id,)).fetchall()
    if not market_ents:
        return None  # 시장과 무관한 개인 메모 — 세계관 지식으로 편입하지 않음
    statement = " ".join(content.split())[:500]
    from pipeline.consolidation import _find_similar_knowledge, _merge_into
    similar = _find_similar_knowledge(conn, statement)
    if similar:
        _merge_into(conn, similar, market_ents[0]["entity_id"],
                    [{"id": doc_id, "independent": True, "published_at": observed_at}])
        return similar
    cur = conn.execute("""
        INSERT INTO knowledge (statement, epistemic_status, review_status, pace_layer, model, valid_from)
        VALUES (?, ?, 'active', ?, 'user', ?)""",
        (statement, "observed" if epistemic == "fact" else "hypothesis",
         _classify_layer(statement), observed_at))
    kid = cur.lastrowid
    for e in market_ents:
        conn.execute("INSERT OR IGNORE INTO knowledge_entities (knowledge_id, entity_id) VALUES (?, ?)",
                     (kid, e["entity_id"]))
    conn.execute("""
        INSERT INTO knowledge_evidence (knowledge_id, doc_id, stance, independent, observed_at)
        VALUES (?, ?, 'support', 1, ?)""", (kid, doc_id, observed_at))
    conn.commit()
    _seed_evidence(conn, kid, statement, exclude={doc_id})
    from pipeline.falsifiers import generate_falsifiers
    generate_falsifiers(conn, kid, statement)
    return kid


def _seed_evidence(conn, kid: int, statement: str, exclude: set[int]):
    """기존 수집분에서 초기 증거 탐색 — K2 스캔은 문서 단위 마크라 새 지식은
    미래 문서만 보게 됨. 주입 시점에 검색 top-5를 판정해 과거분을 보정한다."""
    try:
        from pipeline.search import search
        from pipeline.contradiction import _judge_stance
        hits = search(statement, k=5)
    except Exception:
        return
    for h in hits:
        if h["doc_id"] in exclude:
            continue
        doc = conn.execute(
            "SELECT id, title, published_at, substr(markdown,1,1200) ex FROM raw_documents WHERE id=?",
            (h["doc_id"],)).fetchone()
        if not doc:
            continue
        stance = _judge_stance(statement, doc["title"] or "", doc["ex"])
        if stance not in ("SUPPORT", "REFUTE"):
            continue
        from pipeline.contradiction import _is_independent
        from pipeline.consolidation import _embeddings
        emb = _embeddings(conn, [doc["id"]]).get(doc["id"])
        conn.execute("""
            INSERT INTO knowledge_evidence (knowledge_id, doc_id, stance, independent, observed_at)
            VALUES (?, ?, ?, ?, ?)""",
            (kid, doc["id"], stance.lower(), int(_is_independent(conn, kid, emb)),
             doc["published_at"] or datetime.now(timezone.utc).isoformat()))
    # 시딩 결과로 즉시 승격 가능 여부 판정 (K2와 동일 규칙)
    r = conn.execute("""
        SELECT SUM(stance='support' AND independent) s FROM knowledge_evidence
        WHERE knowledge_id=?""", (kid,)).fetchone()
    if (r["s"] or 0) >= 2:
        conn.execute("""UPDATE knowledge SET epistemic_status='corroborated',
            corroborated_at=datetime('now') WHERE id=? AND epistemic_status IN ('observed','hypothesis')""",
            (kid,))
    conn.commit()


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
