"""텔레그램 봇 양방향 — 주머니 속 옴니바.

- 백엔드(FastAPI) startup에서 데몬 스레드로 long-polling (서버 켜져 있는 동안 응답)
- 보안: TELEGRAM_CHAT_ID와 일치하는 채팅에만 응답
- 라우팅: 종목명/별칭 → 최신 요약+언급+신호 / '/브리핑' → 아침 브리핑 /
          문장형 → RAG 질문 (수집 문서 근거) / 그 외 → 도움말
- 콜백: 아침 브리핑의 inline 버튼(D-107) — `n:{entity_id}`=주제 내러티브 생성,
        `y:{doc_id}`=유튜브 정리본. 생성이 수십 초~수 분이라 즉시 ack + 선응답 후
        **데몬 스레드**에서 돌린다 (폴링 루프를 막지 않게). 결과는 같은 대화로 회신.
- TELEGRAM_POLLING=0 으로 폴링 비활성 (테스트 인스턴스 충돌 방지)
"""
import json
import os
import threading
import time

import requests

from database import get_connection

_started = False
TG_LIMIT = 4000            # 텔레그램 메시지 상한(4096)에 여유
_inflight: set[str] = set()   # 같은 버튼 연타로 opus가 중복 기동되지 않게
_inflight_lock = threading.Lock()


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{method}"


def _send(chat_id: str, text: str):
    """긴 본문은 문단 경계로 나눠 연속 발송 — 내러티브 정리본이 상한을 넘기 때문.

    빈 문자열은 보내지 않는다 — 핸들러가 이미 직접 발송한 경우("" 반환)의 신호.
    """
    if not (text or "").strip():
        return
    for chunk in _chunks(text):
        try:
            requests.post(_api("sendMessage"), json={"chat_id": chat_id, "text": chunk}, timeout=15)
        except Exception:
            return


def _chunks(text: str) -> list[str]:
    if len(text) <= TG_LIMIT:
        return [text]
    out, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > TG_LIMIT:
            if cur:
                out.append(cur)
            # 한 문단이 통째로 상한을 넘으면 강제 절단
            while len(para) > TG_LIMIT:
                out.append(para[:TG_LIMIT])
                para = para[TG_LIMIT:]
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        out.append(cur)
    return out


def _find_company(conn, q: str):
    """정식명 → 활성 키워드/별칭 → 전방일치 순으로 종목 해석."""
    row = conn.execute(
        "SELECT id, name, aliases FROM entities WHERE type='company' AND name=?", (q,)).fetchone()
    if row:
        return row
    row = conn.execute("""
        SELECT e.id, e.name, e.aliases FROM entity_keywords ek
        JOIN entities e ON ek.entity_id = e.id
        WHERE ek.keyword=? AND (ek.status='active' OR ek.status IS NULL)""", (q,)).fetchone()
    if row:
        return row
    return conn.execute("""
        SELECT id, name, aliases FROM entities
        WHERE type='company' AND name LIKE ? || '%' ORDER BY length(name) LIMIT 1""", (q,)).fetchone()


def _stock_brief(conn, ent) -> str:
    lines = [f"📌 {ent['name']} ({ent['aliases'] or '-'})"]
    dig = conn.execute("""
        SELECT period_start, digest, insights FROM entity_digests
        WHERE entity_id=? AND period='1d' ORDER BY period_start DESC LIMIT 1""", (ent["id"],)).fetchone()
    if dig:
        lines.append(f"\n[{dig['period_start']} 요약]")
        if dig["insights"]:
            lines.append(f"💡 {dig['insights']}")
        lines.append((dig["digest"] or "").replace("### ", "· ")[:800])
    sig = conn.execute("""
        SELECT signal_type, date, payload_json FROM signals
        WHERE entity_id=? ORDER BY date DESC LIMIT 1""", (ent["id"],)).fetchone()
    if sig:
        p = json.loads(sig["payload_json"] or "{}")
        if sig["signal_type"] == "mention_surge":
            lines.append(f"\n📈 {sig['date']} 언급 급증 — 7일 {p.get('count_7d')}회")
        elif sig["signal_type"] == "high_52w":
            lines.append(f"\n📈 {sig['date']} 52주 신고가 (+{p.get('breakout_pct')}%)")
    docs = conn.execute("""
        SELECT rd.title, rd.published_at FROM entity_links el
        JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type='stock'
        ORDER BY rd.published_at DESC LIMIT 3""", (ent["id"],)).fetchall()
    if docs:
        lines.append("\n최근 언급:")
        for d in docs:
            lines.append(f"· {(d['title'] or '')[:60]} ({(d['published_at'] or '')[:10]})")
    if len(lines) == 1:
        lines.append("아직 수집된 언급이 없습니다.")
    return "\n".join(lines)


def handle_message(text: str, chat_id: str | None = None) -> str:
    """메시지 → 응답 텍스트 (폴링과 분리 — 단위 테스트 가능).

    chat_id: 텔레그램 사용자 식별 — 스레드·대화 내역이 사용자별로 분리된다.
    """
    q = (text or "").strip()
    if not q:
        return "종목명, 질문, 또는 /브리핑"

    if q in ("/start", "/help", "help", "도움말", "?"):
        return (
            "📟 Explorer 봇 — 주머니 속 리서치 터미널\n"
            "\n"
            "1️⃣ 종목 조회 — 종목명이나 별칭을 그대로 보내세요\n"
            "   예: 삼성전자 · 하이닉스 · 슼하\n"
            "   → 최신 1D 요약, 새로운 시각, 신호, 최근 언급 3건\n"
            "\n"
            "2️⃣ AI 질문 — 문장으로 물어보세요 (수집 문서 근거)\n"
            "   예: 하이닉스 ADR 이후 수급 얘기 정리해줘\n"
            "   → 출처 있는 답변 + 갭(근거 부족·모순) 표시. ~30초 소요\n"
            "\n"
            "3️⃣ 기억해: … — 내 지식을 시스템에 저장\n"
        "   예: 기억해: 삼성전자는 노조 성과급 이슈로 골머리\n"
        "   → 검색·답변·요약이 이 지식을 활용 (기억해(사실): 로 사실 표시)\n"
        "\n"
        "4️⃣ /briefing — 아침 브리핑 다시 받기\n"
            "   (평일 08:00 자동 발송: 기계가 먼저 말하는 3줄+오늘 일정)\n"
            "\n"
            "ℹ️ 답변은 구독 중인 텔레그램·블로그에서 수집된 문서 기반이며,\n"
            "   AI 요약·해석은 참고용입니다 (투자 판단은 사람이)."
        )

    if q in ("/briefing", "/브리핑", "브리핑"):
        from pipeline.notify import compose_briefing
        composed = compose_briefing()
        if not composed:
            return "오늘 브리핑 내용이 없습니다."
        # 재발송은 버튼까지 그대로 — 아침에 못 누른 것을 여기서 누를 수 있게
        if chat_id:
            _send_with_keyboard(chat_id, composed[0], composed[1])
            return ""
        return composed[0]

    # P2-0: 명령어 제외 전 문답을 대화로 적재 (질문 = 사용자 의도 데이터)
    from pipeline.conversations import log_exchange_safe

    # '기억해: …' — 지식 주입 (knowledge-system ①)
    from pipeline.knowledge import parse_remember
    remembered = parse_remember(q)
    if remembered:
        from pipeline.knowledge import inject_knowledge
        content, epistemic = remembered
        try:
            r = inject_knowledge(content, epistemic)
            ents = f"\n연결: {', '.join(r['entities'])}" if r["entities"] else ""
            out = f"💾 지식으로 저장 ({'사실' if epistemic == 'fact' else '가설'}){ents}"
        except Exception as e:
            out = f"저장 실패: {str(e)[:80]}"
        log_exchange_safe(q, out, channel="telegram", chat_id=chat_id)
        return out

    conn = get_connection()
    # 짧은 입력은 종목 조회 시도
    if len(q) <= 12 and " " not in q:
        ent = _find_company(conn, q)
        if ent:
            out = _stock_brief(conn, ent)
            conn.close()
            log_exchange_safe(q, out, channel="telegram", anchor_entity_id=ent["id"], chat_id=chat_id)
            return out
    conn.close()

    # 문장형 → RAG (웹 /chat과 동일 엔진 + 동일하게 스레드 맥락 전달)
    if len(q) >= 8:
        from pipeline.conversations import find_telegram_thread, thread_history
        from pipeline.rag import ask
        thread_id = find_telegram_thread(chat_id)   # 이 사용자의 30분 윈도우 스레드
        history = thread_history(thread_id) if thread_id else None
        try:
            r = ask(q, history=history)
        except Exception as e:
            return f"답변 생성 실패: {e}"
        if not r.get("answer"):
            log_exchange_safe(q, None, channel="telegram", conversation_id=thread_id, chat_id=chat_id)
            return "관련 수집 문서가 없어 답할 수 없습니다."
        parts = [r["answer"][:2500]]
        if r.get("gaps"):
            parts.append("\n⚠ " + " / ".join(g["note"][:60] for g in r["gaps"][:2]))
        parts.append(f"\n(출처 {len(r.get('citations', []))}건 · AI 종합 — 검증 필요)")
        log_exchange_safe(q, r["answer"], citations=r.get("citations"), gaps=r.get("gaps"),
                          model=r.get("model"), channel="telegram",
                          conversation_id=thread_id, chat_id=chat_id)
        return "\n".join(parts)

    log_exchange_safe(q, None, channel="telegram", chat_id=chat_id)
    return "찾지 못했습니다. 종목명(예: 삼성전자) 또는 문장형 질문을 보내주세요. 사용법은 /help"


def _send_with_keyboard(chat_id: str, text: str, keyboard: dict | None):
    """버튼 달린 본문 발송 — 긴 본문은 나누되 키보드는 마지막 조각에만 붙인다."""
    chunks = _chunks(text)
    for i, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk}
        if keyboard and i == len(chunks) - 1:
            payload["reply_markup"] = keyboard
        try:
            requests.post(_api("sendMessage"), json=payload, timeout=15)
        except Exception:
            return


def _answer_callback(cq_id: str, text: str = ""):
    """텔레그램은 콜백을 몇 초 안에 ack하지 않으면 버튼이 멈춘 것처럼 보인다."""
    try:
        requests.post(_api("answerCallbackQuery"),
                      json={"callback_query_id": cq_id, "text": text[:200]}, timeout=10)
    except Exception:
        pass


def _run_narrative(entity_id: int) -> str:
    """주제 버튼 — 기존 compute_narrative를 그대로 호출(멱등: 문서집합 불변이면 캐시)."""
    conn = get_connection()
    row = conn.execute("SELECT name FROM entities WHERE id=?", (entity_id,)).fetchone()
    conn.close()
    if not row:
        return "주제를 찾을 수 없습니다."
    topic = row["name"]

    from pipeline.narrative import compute_narrative
    r = compute_narrative(topic)
    status = r.get("status")
    if status == "not_found":
        return f"'{topic}' — 그래프에 없는 주제입니다."
    if status == "empty":
        return f"'{topic}' — 관련 문서가 3건 미만이라 서사를 만들 수 없습니다."
    if status == "unavailable" and not r.get("narrative"):
        return f"'{topic}' — LLM 엔진 미가용으로 생성하지 못했습니다."
    head = f"🧠 {r.get('title') or topic}"
    if status == "cached":
        head += "  (기존 생성분 — 새 문서 없음)"
    return f"{head}\n\n{r.get('narrative') or ''}"


def _run_youtube(doc_id: int) -> str:
    """영상 버튼 — spine_doc.get_document의 lazy 재요약 경로를 그대로 탄다."""
    from routers.spine_doc import get_document
    try:
        doc = get_document(doc_id)
    except Exception as e:  # noqa: BLE001 — 404 등
        return f"문서를 열 수 없습니다 ({type(e).__name__})."
    body = (doc.content or "").strip()
    if not body:
        return f"📺 {doc.title}\n\n정리본이 비어 있습니다 (자막 없음)."
    return f"📺 {doc.channel or '유튜브'} — {doc.title}\n{doc.url}\n\n{body}"


_CALLBACKS = {
    "n": (_run_narrative, "내러티브"),
    "y": (_run_youtube, "정리본"),
}


def handle_callback(data: str, chat_id: str, cq_id: str) -> None:
    """브리핑 버튼 처리 — 즉시 ack + 선응답 후 생성은 데몬 스레드로."""
    kind, _, raw = (data or "").partition(":")
    entry = _CALLBACKS.get(kind)
    if not entry or not raw.isdigit():
        _answer_callback(cq_id, "알 수 없는 버튼")
        return
    fn, label = entry

    key = f"{chat_id}:{data}"
    with _inflight_lock:
        if key in _inflight:
            _answer_callback(cq_id, "이미 생성 중입니다")
            return
        _inflight.add(key)

    _answer_callback(cq_id, f"{label} 생성 시작 — 완료되면 보내드립니다")
    _send(chat_id, f"🔎 {label} 생성 중… 1~2분 걸립니다")

    def _work():
        try:
            _send(chat_id, fn(int(raw)))
        except Exception as e:  # noqa: BLE001 — 사용자에게 사유를 돌려준다
            _send(chat_id, f"생성 실패 — {type(e).__name__}: {str(e)[:200]}")
        finally:
            with _inflight_lock:
                _inflight.discard(key)

    threading.Thread(target=_work, daemon=True, name=f"tg-{kind}-{raw}").start()


def _allowed_chats() -> set[str]:
    """허용 채팅: TELEGRAM_CHAT_ID(본인) + TELEGRAM_EXTRA_CHAT_IDS(콤마 구분 — 친구/그룹)."""
    ids = {os.getenv("TELEGRAM_CHAT_ID", "").strip()}
    ids |= {x.strip() for x in os.getenv("TELEGRAM_EXTRA_CHAT_IDS", "").split(",")}
    return {i for i in ids if i}


def _poll_loop():
    allowed = _allowed_chats()
    offset = None
    while True:
        try:
            resp = requests.get(_api("getUpdates"),
                                params={"timeout": 50, "offset": offset}, timeout=60)
            for u in resp.json().get("result", []):
                offset = u["update_id"] + 1

                cq = u.get("callback_query")
                if cq:
                    sender = str((cq.get("message") or {}).get("chat", {}).get("id"))
                    if sender in allowed:      # 허용 목록만 (보안)
                        handle_callback(cq.get("data", ""), sender, cq["id"])
                    continue

                msg = u.get("message") or {}
                sender = str(msg.get("chat", {}).get("id"))
                if sender not in allowed:
                    continue  # 허용 목록만 (보안)
                text = msg.get("text", "")
                if not text:
                    continue
                if len(text) >= 15:  # 긴 질문은 시간이 걸림 — 선응답
                    _send(sender, "🔎 찾아보는 중…")
                _send(sender, handle_message(text, chat_id=sender))
        except Exception:
            time.sleep(10)


def start_bot():
    """FastAPI startup에서 호출. 토큰·chat 미설정 또는 TELEGRAM_POLLING=0이면 no-op."""
    global _started
    if _started:
        return
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        return
    if os.getenv("TELEGRAM_POLLING", "1") != "1":
        return
    _started = True
    try:
        requests.post(_api("setMyCommands"), json={"commands": [
            {"command": "help", "description": "사용법 — 종목 조회·AI 질문·브리핑"},
            {"command": "briefing", "description": "아침 브리핑 다시 받기"},
        ]}, timeout=10)
    except Exception:
        pass
    threading.Thread(target=_poll_loop, daemon=True, name="telegram-bot").start()
