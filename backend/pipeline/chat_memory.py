"""멀티턴 메모리 — 스레드 노트(컴팩션)·상태·교차 스레드 회상 (docs/specs/chat-agent.md §3, D-131).

층:
- 스레드 원문: chat_messages (append-only, 항상)
- 스레드 노트: conversations.summary — 4절 구조화 노트(주제/확인된 것/미해결/사용자 관심), haiku low.
  메시지 ≥ NOTE_MIN_MESSAGES 이고 노트 이후 ≥ NOTE_EVERY 메시지 쌓이면 갱신.
- 스레드 상태: conversations.state_json — 엔티티·마지막 intent·도구·근거 doc_ids·note_upto (코드, 매 턴)
- 교차 스레드 회상: 같은 엔티티가 걸린 다른 스레드의 노트 ≤2 (참고용, 근거 아님)

불변: 노트·상태·답변은 검색 인덱스에 넣지 않는다(D-004 ③). 자동 지식 추출은 하지 않는다.
"""
import json
import os

from database import get_connection
from pipeline import llm

RECENT_MESSAGES = 4        # 종합·라우터에 전문으로 넣는 최근 메시지 수
RECENT_CHARS = 500
NOTE_MIN_MESSAGES = 8
NOTE_EVERY = 4
NOTE_MAX_CHARS = 600
RELATED_MAX = 2


def load_context(conversation_id: int | None, question: str) -> dict:
    """턴 시작 — {note, state, recent[], related[]}. recent는 방금 적재된 질문을 제외한 최근 메시지."""
    ctx = {"note": None, "state": {}, "recent": [], "related": []}
    if conversation_id is None:
        return ctx
    conn = get_connection()
    try:
        conv = conn.execute("SELECT summary, state_json, chat_id, channel FROM conversations WHERE id=?",
                            (conversation_id,)).fetchone()
        if not conv:
            return ctx
        ctx["note"] = conv["summary"]
        try:
            ctx["state"] = json.loads(conv["state_json"] or "{}")
        except ValueError:
            ctx["state"] = {}
        rows = [dict(r) for r in conn.execute(
            "SELECT id, role, content FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conversation_id, RECENT_MESSAGES + 1))][::-1]
        if rows and rows[-1]["role"] == "user" and rows[-1]["content"] == question:
            rows = rows[:-1]
        ctx["recent"] = rows[-RECENT_MESSAGES:]
        ctx["related"] = _related_threads(conn, conversation_id, ctx["state"].get("entities") or [],
                                          conv["chat_id"])
    finally:
        conn.close()
    return ctx


def _related_threads(conn, conversation_id: int, entities: list[dict], chat_id) -> list[dict]:
    """같은 엔티티가 걸린 다른 스레드의 노트 — 같은 사용자(chat_id) 것만."""
    ids = [e.get("id") for e in entities if e.get("id")]
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    rows = conn.execute(f"""
        SELECT DISTINCT c.id, c.title, c.summary, c.updated_at FROM conversations c
        LEFT JOIN chat_messages m ON m.conversation_id=c.id
        LEFT JOIN chat_entity_links cel ON cel.message_id=m.id
        WHERE c.id != ? AND c.summary IS NOT NULL AND c.chat_id IS ?
          AND (c.anchor_entity_id IN ({ph}) OR cel.entity_id IN ({ph}))
        ORDER BY c.updated_at DESC LIMIT ?""", (conversation_id, chat_id, *ids, *ids, RELATED_MAX)).fetchall()
    return [{"id": r["id"], "title": r["title"], "note": r["summary"], "updated_at": r["updated_at"]} for r in rows]


def context_block(ctx: dict, chars: int = RECENT_CHARS, skip_ids: set[int] | None = None) -> str:
    """종합·라우터 공용 대화 맥락 블록.

    skip_ids: 여기서 뺄 메시지 id — 인용된 답변은 별도 블록에 **전문**으로 들어가므로
    500자 잘린 사본을 중복으로 싣지 않는다 (D-146).
    """
    parts = []
    if ctx.get("note"):
        parts.append("[이 스레드의 작업 노트 — 지금까지의 맥락]\n" + ctx["note"])
    recent = [m for m in (ctx.get("recent") or []) if not (skip_ids and m.get("id") in skip_ids)]
    if recent:
        lines = [f"{'사용자' if m['role'] == 'user' else '이전 답변'}: {(m['content'] or '')[:chars]}" for m in recent]
        parts.append("[최근 대화]\n" + "\n".join(lines))
    if ctx.get("related"):
        lines = [f"- ({r['updated_at'][:10]}) {r['title']}: {(r['note'] or '')[:300]}" for r in ctx["related"]]
        parts.append("[같은 주제를 다룬 이전 스레드의 노트 — 참고용. 근거가 아니므로 인용하지 말 것]\n" + "\n".join(lines))
    return "\n\n".join(parts)


def update_state(conversation_id: int, *, entities: list[dict], intent: str | None,
                 tools: list[str], doc_ids: list[int], last_citations: list[dict] | None = None) -> None:
    """턴 종료 — 결정적 상태 갱신 (LLM 0)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT state_json FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        try:
            state = json.loads((row["state_json"] if row else None) or "{}")
        except ValueError:
            state = {}
        merged = {e["name"]: e for e in (state.get("entities") or []) if e.get("name")}
        for e in entities:
            if e.get("name"):
                merged[e["name"]] = e
        state.update({
            "entities": list(merged.values())[-8:],
            "last_intent": intent,
            "last_tools": tools,
            "doc_ids": (doc_ids + [d for d in state.get("doc_ids", []) if d not in doc_ids])[:10],
            "last_citations": (last_citations or [])[:10],   # 후속 "그 문서 더 보여줘" → open_doc
        })
        conn.execute("UPDATE conversations SET state_json=? WHERE id=?",
                     (json.dumps(state, ensure_ascii=False), conversation_id))
        conn.commit()
    finally:
        conn.close()


def maybe_compact(conversation_id: int) -> bool:
    """조건 충족 시 작업 노트 갱신(haiku low). 반환: 갱신했는가."""
    conn = get_connection()
    try:
        conv = conn.execute("SELECT summary, state_json FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conv:
            return False
        try:
            state = json.loads(conv["state_json"] or "{}")
        except ValueError:
            state = {}
        msgs = [dict(r) for r in conn.execute(
            "SELECT id, role, content FROM chat_messages WHERE conversation_id=? ORDER BY id", (conversation_id,))]
        if len(msgs) < NOTE_MIN_MESSAGES:
            return False
        upto = state.get("note_upto") or 0
        new = [m for m in msgs if m["id"] > upto]
        if len(new) < NOTE_EVERY:
            return False
    finally:
        conn.close()

    transcript = "\n".join(f"{'사용자' if m['role'] == 'user' else '답변'}: {(m['content'] or '')[:700]}" for m in new)
    prompt = (
        ("[기존 노트]\n" + conv["summary"] + "\n\n") if conv["summary"] else ""
    ) + f"[노트 이후 새 대화]\n{transcript}\n\n위를 반영해 노트를 다시 써라."
    system = (
        "너는 투자 리서치 대화의 작업 노트를 관리한다. 이 노트는 다음 턴에서 대화 맥락을 대신한다.\n"
        f"형식(마크다운, {NOTE_MAX_CHARS}자 이내):\n## 주제\n## 확인된 것 (근거가 제시된 사실·판단만)\n## 미해결 (아직 답 못 한 질문·후속)\n## 사용자 관심 (선호·관점·반복 질문)\n"
        "규칙: 대화에 있는 내용만, 지어내지 말 것. 내부 코드·영문 상태값 금지. 노트 본문만 출력."
    )
    try:
        res = llm.run(prompt, system=system, model=os.getenv("CHAT_NOTE_MODEL", "haiku"), effort="low",
                      tools=(), timeout=120, job="chat.note")
    except Exception:
        return False
    note = (res.text or "").strip()[:NOTE_MAX_CHARS + 200]
    if not note:
        return False
    conn = get_connection()
    try:
        state["note_upto"] = msgs[-1]["id"]
        conn.execute("UPDATE conversations SET summary=?, state_json=? WHERE id=?",
                     (note, json.dumps(state, ensure_ascii=False), conversation_id))
        conn.commit()
    finally:
        conn.close()
    return True


def set_attached_documents(conversation_id: int, doc_ids: list[int]) -> None:
    """Explicit reading selection; [] clears it. Retained independently of used citations."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT state_json FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        state = json.loads((row['state_json'] if row else None) or '{}')
        state['attached_doc_ids'] = doc_ids[:12]
        conn.execute('UPDATE conversations SET state_json=? WHERE id=?',
                     (json.dumps(state, ensure_ascii=False), conversation_id))
        conn.commit()
    finally:
        conn.close()
