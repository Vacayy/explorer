"""대화 조회 API — P2-1 '내가 물어본 것들' (P2-2 스레드 UI도 재사용) + 진행 스트림(SSE, D-130)."""
import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
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
    route: dict | None = None     # D-131 라우팅·도구 로그 — FE '답변 경로' 토글
    created_at: str


class ConversationDetail(BaseModel):
    id: int
    title: str | None
    channel: str
    messages: list[ChatMessage]


def _owner_filter() -> tuple[str, list]:
    """웹 대화 목록은 오너 것만 — 친구(TELEGRAM_EXTRA_CHAT_IDS) 스레드 비노출 (A7 프라이버시)."""
    owner = os.getenv("TELEGRAM_CHAT_ID", "")
    return "(c.channel='web' OR c.chat_id IS NULL OR c.chat_id=?)", [owner]


@router.get("", response_model=list[ConversationItem])
def list_conversations(stock: str | None = Query(None, description="종목코드 — 앵커 또는 질문 링크 기준"),
                       limit: int = Query(20, ge=1, le=100)):
    conn = get_connection()
    owner_sql, owner_params = _owner_filter()
    if stock:
        rows = conn.execute("""
            SELECT DISTINCT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at,
                   (SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) n
            FROM conversations c
            LEFT JOIN chat_messages m ON m.conversation_id = c.id
            LEFT JOIN chat_entity_links cel ON cel.message_id = m.id
            WHERE (c.anchor_entity_id = (SELECT id FROM entities WHERE type='company' AND aliases=?)
               OR cel.entity_id = (SELECT id FROM entities WHERE type='company' AND aliases=?))
              AND {owner_sql}
            ORDER BY c.updated_at DESC LIMIT ?
        """.format(owner_sql=owner_sql), (stock, stock, *owner_params, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT c.id, c.title, c.channel, c.anchor_entity_id, c.updated_at,
                   (SELECT count(*) FROM chat_messages m WHERE m.conversation_id=c.id) n
            FROM conversations c WHERE {owner_sql}
            ORDER BY c.updated_at DESC LIMIT ?
        """.format(owner_sql=owner_sql), (*owner_params, limit)).fetchall()
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
        SELECT id, role, content, citations_json, gaps_json, model, route_json, created_at
        FROM chat_messages WHERE conversation_id=? ORDER BY id""", (conversation_id,)).fetchall()
    conn.close()
    return ConversationDetail(
        id=conv["id"], title=conv["title"], channel=conv["channel"],
        messages=[ChatMessage(
            id=m["id"], role=m["role"], content=m["content"],
            citations=json.loads(m["citations_json"]) if m["citations_json"] else None,
            gaps=json.loads(m["gaps_json"]) if m["gaps_json"] else None,
            model=m["model"], route=json.loads(m["route_json"]) if m["route_json"] else None,
            created_at=m["created_at"]) for m in msgs])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/{conversation_id}/stream")
async def stream_conversation(conversation_id: int):
    """답변 생성 진행 스트림 (SSE) — status(단계)·delta(본문 조각)·done.

    가속기일 뿐 진실원천은 DB: 생성 중인 스트림이 없으면 404 → FE는 폴링으로 복귀.
    LLM 토큰 비용은 폴링과 같다(같은 출력을 조각으로 받을 뿐). 연결 1개/생성 1건.
    """
    from pipeline.chat import get_stream
    st = get_stream(conversation_id)
    if st is None:
        raise HTTPException(404, "진행 중인 생성이 없습니다")

    async def gen():
        sent = 0
        last_status = None
        while True:
            text, status, done = st.snapshot()
            if status != last_status:
                last_status = status
                yield _sse("status", {"text": status})
            if len(text) > sent:
                yield _sse("delta", {"text": text[sent:]})
                sent = len(text)
            elif len(text) < sent:      # visible_text가 META 경계에서 꼬리를 걷어낸 경우
                yield _sse("reset", {"text": text})
                sent = len(text)
            if done:
                yield _sse("done", {})
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
