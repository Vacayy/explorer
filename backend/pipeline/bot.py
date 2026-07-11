"""텔레그램 봇 양방향 — 주머니 속 옴니바.

- 백엔드(FastAPI) startup에서 데몬 스레드로 long-polling (서버 켜져 있는 동안 응답)
- 보안: TELEGRAM_CHAT_ID와 일치하는 채팅에만 응답
- 라우팅: 종목명/별칭 → 최신 요약+언급+신호 / '/브리핑' → 아침 브리핑 /
          문장형 → RAG 질문 (수집 문서 근거) / 그 외 → 도움말
- TELEGRAM_POLLING=0 으로 폴링 비활성 (테스트 인스턴스 충돌 방지)
"""
import json
import os
import threading
import time

import requests

from database import get_connection

_started = False


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{method}"


def _send(chat_id: str, text: str):
    try:
        requests.post(_api("sendMessage"), json={"chat_id": chat_id, "text": text[:4000]}, timeout=15)
    except Exception:
        pass


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


def handle_message(text: str) -> str:
    """메시지 → 응답 텍스트 (폴링과 분리 — 단위 테스트 가능)."""
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
            "3️⃣ /briefing — 아침 브리핑 다시 받기\n"
            "   (평일 08:00 자동 발송: 기계가 먼저 말하는 3줄+오늘 일정)\n"
            "\n"
            "ℹ️ 답변은 구독 중인 텔레그램·블로그에서 수집된 문서 기반이며,\n"
            "   AI 요약·해석은 참고용입니다 (투자 판단은 사람이)."
        )

    if q in ("/briefing", "/브리핑", "브리핑"):
        from pipeline.notify import _compose_briefing
        return _compose_briefing() or "오늘 브리핑 내용이 없습니다."

    # P2-0: 명령어 제외 전 문답을 대화로 적재 (질문 = 사용자 의도 데이터)
    from pipeline.conversations import log_exchange_safe

    conn = get_connection()
    # 짧은 입력은 종목 조회 시도
    if len(q) <= 12 and " " not in q:
        ent = _find_company(conn, q)
        if ent:
            out = _stock_brief(conn, ent)
            conn.close()
            log_exchange_safe(q, out, channel="telegram", anchor_entity_id=ent["id"])
            return out
    conn.close()

    # 문장형 → RAG
    if len(q) >= 8:
        from pipeline.rag import ask
        try:
            r = ask(q)
        except Exception as e:
            return f"답변 생성 실패: {e}"
        if not r.get("answer"):
            log_exchange_safe(q, None, channel="telegram")
            return "관련 수집 문서가 없어 답할 수 없습니다."
        parts = [r["answer"][:2500]]
        if r.get("gaps"):
            parts.append("\n⚠ " + " / ".join(g["note"][:60] for g in r["gaps"][:2]))
        parts.append(f"\n(출처 {len(r.get('citations', []))}건 · AI 종합 — 검증 필요)")
        log_exchange_safe(q, r["answer"], citations=r.get("citations"), gaps=r.get("gaps"),
                          model=r.get("model"), channel="telegram")
        return "\n".join(parts)

    log_exchange_safe(q, None, channel="telegram")
    return "찾지 못했습니다. 종목명(예: 삼성전자) 또는 문장형 질문을 보내주세요. 사용법은 /help"


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
                msg = u.get("message") or {}
                sender = str(msg.get("chat", {}).get("id"))
                if sender not in allowed:
                    continue  # 허용 목록만 (보안)
                text = msg.get("text", "")
                if not text:
                    continue
                if len(text) >= 15:  # 긴 질문은 시간이 걸림 — 선응답
                    _send(sender, "🔎 찾아보는 중…")
                _send(sender, handle_message(text))
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
