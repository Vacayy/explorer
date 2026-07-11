"""대화 조회 API — P2-1 '내가 물어본 것들' (P2-2 스레드 UI도 재사용)."""
import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/conversations", tags=["spine"])


class ConversationItem(BaseModel):
    id: int
    title: str | None
    channel: str
    anchor_entity_id: int | None
    message_count: int
    updated_at: str


class ChatMessage(BaseModel):
    id: int
    role: str
    content: str
    citations: list | None
    gaps: list | None
    model: str | None
    created_at: str


class ConversationDetail(BaseModel):
    id: int
    title: str | None
    channel: str
    messages: list[ChatMessage]


@router.get("", response_model=list[ConversationItem])
def list_conversations(stock: str | None = Query(None, description="종목코드 — 앵커 또는 질문 링크 기준"),
                       limit: int = Query(20, ge=1, le=100)):
    conn = get_connection()
    if stock:
        rows = conn.execute("""
            SELECT DISTINCT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at,
                   (SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) n
            FROM conversations c
            LEFT JOIN chat_messages m ON m.conversation_id = c.id
            LEFT JOIN chat_entity_links cel ON cel.message_id = m.id
            WHERE c.anchor_entity_id = (SELECT id FROM entities WHERE type='company' AND aliases=?)
               OR cel.entity_id = (SELECT id FROM entities WHERE type='company' AND aliases=?)
            ORDER BY c.updated_at DESC LIMIT ?
        """, (stock, stock, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at,
                   (SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) n
            FROM conversations c ORDER BY c.updated_at DESC LIMIT ?
        """, (limit,)).fetchall()
    conn.close()
    return [ConversationItem(id=r["id"], title=r["title"], channel=r["channel"],
                             anchor_entity_id=r["anchor_entity_id"],
                             message_count=r["n"], updated_at=r["updated_at"]) for r in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int):
    conn = get_connection()
    conv = conn.execute("SELECT id, title, channel FROM conversations WHERE id=?",
                        (conversation_id,)).fetchone()
    if not conv:
        conn.close()
        raise HTTPException(404, "대화를 찾을 수 없습니다")
    msgs = conn.execute("""
        SELECT id, role, content, citations_json, gaps_json, model, created_at
        FROM chat_messages WHERE conversation_id=? ORDER BY id""", (conversation_id,)).fetchall()
    conn.close()
    return ConversationDetail(
        id=conv["id"], title=conv["title"], channel=conv["channel"],
        messages=[ChatMessage(
            id=m["id"], role=m["role"], content=m["content"],
            citations=json.loads(m["citations_json"]) if m["citations_json"] else None,
            gaps=json.loads(m["gaps_json"]) if m["gaps_json"] else None,
            model=m["model"], created_at=m["created_at"]) for m in msgs])
