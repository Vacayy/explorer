"""대화 영속화 — P2-0 (docs/specs/product-v3.md §2).

- 웹(/ask)·텔레그램 봇의 전 문답을 conversations/chat_messages에 적재
- 질문에 종목 엔티티 링크 (store._link와 동일한 결정적 매칭 — LLM 0토큰)
- 에코챔버 방지: AI 답변은 검색 인덱스(doc_fts/doc_vec)에 절대 넣지 않는다
- 텔레그램 스레딩 휴리스틱: 마지막 활동 30분 이내면 같은 스레드 (A9)
- 적재 실패가 답변 경로를 깨면 안 된다 → 호출부는 log_exchange_safe만 사용
"""
import json
import re

from database import get_connection

TELEGRAM_THREAD_WINDOW_MIN = 30


def _boundary_ok(text: str, name: str) -> bool:
    """store._link의 경계 휴리스틱: 앞 경계는 항상, ≤2자 이름은 뒤 경계도 요구."""
    pat = rf"(?<![0-9A-Za-z가-힣]){re.escape(name)}"
    if len(name) <= 2:
        pat += r"(?![0-9A-Za-z가-힣])"
    return re.search(pat, text) is not None


def _match_stocks(conn, text: str) -> set[int]:
    """질문 텍스트에서 종목 결정적 매칭 — 활성 키워드 + 정식명."""
    ids: set[int] = set()
    for row in conn.execute(
        "SELECT entity_id, keyword FROM entity_keywords WHERE status='active' OR status IS NULL"):
        kw = (row["keyword"] or "").strip()
        if kw and kw in text and _boundary_ok(text, kw):
            ids.add(row["entity_id"])
    for row in conn.execute("SELECT id, name FROM entities WHERE type='company'"):
        name = row["name"]
        if name and name in text and _boundary_ok(text, name):
            ids.add(row["id"])
    return ids


def find_telegram_thread(chat_id: str | None) -> int | None:
    """이 사용자(chat_id)의 30분 윈도우 내 마지막 텔레그램 스레드 — 없으면 None."""
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT id FROM conversations WHERE channel='telegram' AND chat_id IS ?
              AND updated_at >= datetime('now', ?)
            ORDER BY updated_at DESC LIMIT 1
        """, (chat_id, f"-{TELEGRAM_THREAD_WINDOW_MIN} minutes")).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def thread_history(conversation_id: int, limit: int = 6) -> list[dict]:
    """스레드의 최근 문답 — RAG 후속질문 맥락용."""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT role, content FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit))][::-1]
    finally:
        conn.close()


def log_question(question: str, *, channel: str = "web",
                 conversation_id: int | None = None,
                 anchor_entity_id: int | None = None,
                 chat_id: str | None = None) -> int:
    """질문만 즉시 적재 (LLM 실행 전) — 진행 중 상태도 서버 상태가 되도록.

    마지막 메시지가 user면 '답변 생성 중'으로 해석된다 (FE 폴링 규약).
    반환: conversation_id.
    """
    conn = get_connection()
    try:
        cid = _resolve_thread(conn, conversation_id, channel, question, anchor_entity_id, chat_id)
        msg_id = conn.execute(
            "INSERT INTO chat_messages (conversation_id, role, content) VALUES (?, 'user', ?)",
            (cid, question)).lastrowid
        for eid in _match_stocks(conn, question):
            conn.execute(
                "INSERT OR IGNORE INTO chat_entity_links (message_id, entity_id, link_type) "
                "VALUES (?, ?, 'stock')", (msg_id, eid))
        conn.commit()
        return cid
    finally:
        conn.close()


def append_assistant(conversation_id: int, content: str, *,
                     citations: list | None = None, gaps: list | None = None,
                     model: str | None = None, route: dict | None = None):
    """답변 적재 — 백그라운드 작업 완료 시 호출. route=라우팅·도구 로그(D-131, '왜 이 답인가')."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO chat_messages (conversation_id, role, content,
                                       citations_json, gaps_json, model, route_json)
            VALUES (?, 'assistant', ?, ?, ?, ?, ?)
        """, (conversation_id, content,
              json.dumps(citations, ensure_ascii=False) if citations else None,
              json.dumps(gaps, ensure_ascii=False) if gaps else None,
              model,
              json.dumps(route, ensure_ascii=False) if route else None))
        conn.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?",
                     (conversation_id,))
        conn.commit()
    finally:
        conn.close()


def _resolve_thread(conn, conversation_id, channel, question, anchor_entity_id,
                    chat_id: str | None = None) -> int:
    if conversation_id is None and channel == "telegram":
        # 사용자(chat_id)별 윈도우 — 다른 사용자의 문답과 절대 섞이지 않는다
        row = conn.execute("""
            SELECT id FROM conversations WHERE channel='telegram' AND chat_id IS ?
              AND updated_at >= datetime('now', ?)
            ORDER BY updated_at DESC LIMIT 1
        """, (chat_id, f"-{TELEGRAM_THREAD_WINDOW_MIN} minutes")).fetchone()
        conversation_id = row["id"] if row else None
    if conversation_id is None:
        return conn.execute(
            "INSERT INTO conversations (title, anchor_entity_id, channel, chat_id) VALUES (?, ?, ?, ?)",
            ((question or "").strip()[:60], anchor_entity_id, channel, chat_id)).lastrowid
    conn.execute("""
        UPDATE conversations SET updated_at=datetime('now'),
            anchor_entity_id=COALESCE(anchor_entity_id, ?)
        WHERE id=?""", (anchor_entity_id, conversation_id))
    return conversation_id


def log_exchange(question: str, answer: str | None, *,
                 citations: list | None = None, gaps: list | None = None,
                 model: str | None = None, channel: str = "web",
                 conversation_id: int | None = None,
                 anchor_entity_id: int | None = None,
                 chat_id: str | None = None) -> int:
    """문답 1회 적재. 반환: conversation_id.

    conversation_id 없으면 새 스레드 생성 — 단 텔레그램은 30분 윈도우 내
    마지막 스레드를 이어간다. anchor는 스레드에 아직 없을 때만 채운다.
    """
    cid = log_question(question, channel=channel, conversation_id=conversation_id,
                       anchor_entity_id=anchor_entity_id, chat_id=chat_id)
    if answer:
        append_assistant(cid, answer, citations=citations, gaps=gaps, model=model)
    return cid


def log_exchange_safe(*args, **kwargs) -> int | None:
    """적재는 부가 기능 — 실패해도 답변 경로를 깨지 않는다."""
    try:
        return log_exchange(*args, **kwargs)
    except Exception:
        return None
