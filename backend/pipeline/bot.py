"""텔레그램 봇 양방향 — 주머니 속 옴니바.

- 백엔드(FastAPI) startup에서 데몬 스레드로 long-polling (서버 켜져 있는 동안 응답)
- 보안: TELEGRAM_CHAT_ID와 일치하는 채팅에만 응답
- 라우팅: 종목명/별칭 → 최신 요약+언급+신호 / '/브리핑' → 아침 브리핑 /
          문장형 → RAG 질문 (웹과 같은 pipeline/chat.generate_answer, 데몬 스레드·말풍선 대체) / 그 외 → 도움말
- 액션: 아침 브리핑의 **본문 인라인 딥링크**(D-109) — `t.me/<bot>?start=n_4740` 을 누르면
        봇이 `/start n_4740` 을 받아 주제 내러티브를, `y_11676` 이면 유튜브 정리본을 생성.
        구 inline 버튼 콜백(`n:4740`, D-107)도 이미 발송된 메시지를 위해 계속 받는다 —
        둘 다 `start_action()` 한 곳으로 모인다.
        생성이 수십 초~수 분이라 즉시 응답 후 **데몬 스레드**에서 돌린다(폴링 비차단).
- 출력: 본문은 마크다운 → 텔레그램 HTML 변환(pipeline/telegram_md.py) 후 parse_mode=HTML.
- TELEGRAM_POLLING=0 으로 폴링 비활성 (테스트 인스턴스 충돌 방지)
"""
import json
import os
import threading
import time

import requests

from database import get_connection

_started = False
_inflight: set[str] = set()   # 같은 링크 연타로 opus가 중복 기동되지 않게
_inflight_lock = threading.Lock()


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{method}"


def _render(text: str, markdown: bool) -> list[str]:
    from pipeline.telegram_md import split_html, to_html
    return split_html(to_html(text) if markdown else text)


def _send(chat_id: str, text: str, markdown: bool = True) -> int | None:
    """본문 발송 → 첫 메시지 id. 마크다운 → HTML 변환 후 태그 경계를 지켜 분할(D-109).

    빈 문자열은 보내지 않는다 — 핸들러가 이미 직접 발송한 경우("" 반환)의 신호.
    markdown=False 는 이미 HTML로 조립된 본문(브리핑) 용.
    """
    if not (text or "").strip():
        return None
    first = None
    for chunk in _render(text, markdown):
        mid = _post(chat_id, chunk)
        if mid is None:
            break
        first = first or mid
    return first


def _replace(chat_id: str, message_id: int, text: str, markdown: bool = True) -> None:
    """로딩 말풍선을 결과로 **대체**한다 (D-111).

    '생성 중…'은 진행 표시일 뿐 대화 기록에 남을 내용이 아니다. editMessageText로
    같은 말풍선을 결과로 갈아끼워 잔재를 남기지 않는다. 결과가 여러 조각이면
    첫 조각으로 대체하고 나머지는 이어 보낸다. 편집이 실패하면(메시지 삭제 등)
    placeholder를 지우고 새로 보낸다 — 어느 경로로도 결과는 반드시 도달한다.
    """
    chunks = _render(text, markdown)
    if not chunks:
        _delete(chat_id, message_id)
        return
    if not _edit(chat_id, message_id, chunks[0]):
        _delete(chat_id, message_id)
        _post(chat_id, chunks[0])
    for chunk in chunks[1:]:
        _post(chat_id, chunk)


def _call(method: str, payload: dict):
    """텔레그램 API 1회. 마크업 파싱 실패(400)는 평문으로 1회 구제 — 서식보다 내용 전달이 우선."""
    try:
        r = requests.post(_api(method), json=payload, timeout=15)
    except Exception:
        return None
    if r.status_code == 200:
        return (r.json() or {}).get("result")
    if r.status_code == 400 and payload.get("parse_mode"):
        if "not modified" in r.text:      # 편집 결과가 원문과 동일 — 실패가 아니다
            return True
        import html as _html
        import re as _re
        plain = dict(payload)
        plain.pop("parse_mode")
        plain["text"] = _html.unescape(_re.sub(r"<[^>]+>", "", payload.get("text", "")))
        print(f"[bot] 마크업 파싱 실패 → 평문 재시도: {r.text[:160]}", flush=True)
        return _call(method, plain)
    return None


def _post(chat_id: str, text: str) -> int | None:
    r = _call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    return r.get("message_id") if isinstance(r, dict) else None


def _edit(chat_id: str, message_id: int, text: str) -> bool:
    return _call("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                     "text": text, "parse_mode": "HTML"}) is not None


def _delete(chat_id: str, message_id: int) -> None:
    _call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


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

    # 브리핑 본문 딥링크 — `/start n_4740` (D-109). 도움말(/start 단독)보다 먼저 판별.
    if q.startswith("/start ") and chat_id:
        payload = q[len("/start "):].strip()
        kind, _, ident = payload.partition("_")
        return start_action(kind, ident, chat_id)

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
            "   → 출처 있는 답변 + 갭(근거 부족·모순) 표시. 이어서 물으면 맥락을 기억합니다. ~30초 소요\n"
            "\n"
            "3️⃣ /briefing — 아침 브리핑 다시 받기\n"
            "   (평일 08:00 자동 발송: 3줄 + 어젯밤 미국장 + 어제의 주제 + 유튜브)\n"
            "   본문의 파란 링크를 누르면 내러티브·정리본 생성이 걸립니다\n"
            "\n"
            "ℹ️ 답변은 구독 중인 텔레그램·블로그에서 수집된 문서 기반이며,\n"
            "   AI 요약·해석은 참고용입니다 (투자 판단은 사람이)."
        )

    if q in ("/briefing", "/브리핑", "브리핑"):
        from pipeline.notify import compose_briefing
        body = compose_briefing()
        if not body:
            return "오늘 브리핑 내용이 없습니다."
        # 이미 HTML로 조립된 본문 — 재변환하면 태그가 이스케이프된다
        if chat_id:
            _send(chat_id, body, markdown=False)
            return ""
        return body

    # P2-0: 명령어 제외 전 문답을 대화로 적재 (질문 = 사용자 의도 데이터)
    from pipeline.conversations import log_exchange_safe

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

    # 문장형 → RAG. 웹 /chat과 **같은 함수**(pipeline/chat.generate_answer)를 데몬 스레드에서 —
    # 폴링 스레드를 막지 않고, 로딩 말풍선을 결과로 대체한다(D-111). 스레드는 항상 assistant로 닫힌다.
    if len(q) >= 8:
        from pipeline.chat import generate_answer
        from pipeline.conversations import find_telegram_thread, log_question
        thread_id = find_telegram_thread(chat_id)   # 이 사용자의 30분 윈도우 스레드
        try:
            cid = log_question(q, channel="telegram", conversation_id=thread_id, chat_id=chat_id)
        except Exception as e:  # noqa: BLE001
            return f"질문 적재 실패: {str(e)[:100]}"
        if not chat_id:                               # 단위 테스트 경로 — 동기
            return _format_rag(generate_answer(cid, q))
        pending_id = _post(chat_id, "🔎 찾아보는 중… (~30초)")

        def _work():
            out = _format_rag(generate_answer(cid, q))
            if pending_id:
                _replace(chat_id, pending_id, out)
            else:
                _send(chat_id, out)

        threading.Thread(target=_work, daemon=True, name=f"tg-rag-{cid}").start()
        return ""

    out = "찾지 못했습니다. 종목명(예: 삼성전자) 또는 문장형 질문을 보내주세요. 사용법은 /help"
    log_exchange_safe(q, out, channel="telegram", chat_id=chat_id)
    return out


def _format_rag(r: dict) -> str:
    """generate_answer 결과 → 텔레그램 본문."""
    if r.get("error"):
        return r["error"]
    if not r.get("answer"):
        return "관련 수집 문서가 없어 답할 수 없습니다."
    parts = [r["answer"][:2500]]
    if r.get("gaps"):
        parts.append("\n⚠ " + " / ".join(g["note"][:60] for g in r["gaps"][:2]))
    parts.append(f"\n(출처 {len(r.get('citations', []))}건 · AI 종합 — 검증 필요)")
    return "\n".join(parts)


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


_ACTIONS = {
    "n": (_run_narrative, "내러티브"),
    "y": (_run_youtube, "정리본"),
}


def _pending_text(kind: str, ident: int) -> str:
    """로딩 말풍선 문구 — 이미 만들어져 있으면 '생성'이 아니라 '불러오는' 것이다 (D-111)."""
    if kind == "y":
        conn = get_connection()
        row = conn.execute(
            "SELECT digest_status FROM raw_documents WHERE id=?", (ident,)).fetchone()
        conn.close()
        if row and row["digest_status"] == "ok":
            return "📺 정리본 불러오는 중…"
        return "📺 정리본 생성 중… 1~2분 걸립니다"
    return "🧠 내러티브 준비 중… (새 문서가 있으면 1~2분)"


def start_action(kind: str, ident: str, chat_id: str) -> str:
    """생성 액션 착수. 로딩 말풍선을 띄우고 완료 시 **그 말풍선을 결과로 대체**한다(D-111).

    본문 딥링크(`/start n_4740`)와 구 inline 버튼 콜백(`n:4740`)의 공용 진입점.
    반환값은 호출부가 보낼 문구 — 정상 착수 시에는 이미 직접 발송했으므로 ""."""
    entry = _ACTIONS.get(kind)
    if not entry or not ident.isdigit():
        return "알 수 없는 요청입니다. 사용법은 /help"
    fn, label = entry

    key = f"{chat_id}:{kind}:{ident}"
    with _inflight_lock:
        if key in _inflight:
            return f"이미 {label} 준비 중입니다 — 잠시만요."
        _inflight.add(key)

    pending_id = _post(chat_id, _pending_text(kind, int(ident)))

    def _work():
        try:
            out = fn(int(ident))
        except Exception as e:  # noqa: BLE001 — 사용자에게 사유를 돌려준다
            out = f"생성 실패 — {type(e).__name__}: {str(e)[:200]}"
        try:
            if pending_id:
                _replace(chat_id, pending_id, out)   # 로딩 말풍선 → 결과
            else:
                _send(chat_id, out)                  # 말풍선 확보 실패 시 새 메시지
        finally:
            with _inflight_lock:
                _inflight.discard(key)

    threading.Thread(target=_work, daemon=True, name=f"tg-{kind}-{ident}").start()
    return ""


def handle_callback(data: str, chat_id: str, cq_id: str) -> None:
    """구 inline 버튼(D-107)이 달린 기존 메시지 대응 — 즉시 ack 후 같은 디스패처로."""
    kind, _, ident = (data or "").partition(":")
    _answer_callback(cq_id, "생성 시작 — 완료되면 보내드립니다")
    _send(chat_id, start_action(kind, ident, chat_id))


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
                # 오래 걸리는 경로(RAG·딥링크 액션)는 핸들러가 자체 로딩 말풍선을 띄우고
                # ""를 돌려준다 — 여기서는 즉답 문구만 보낸다 (_send는 빈 문자열을 무시)
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
