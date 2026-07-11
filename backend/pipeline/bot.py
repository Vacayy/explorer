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

    if q in ("/start", "/help", "help", "?"):
        return ("📟 Explorer 봇\n"
                "· 종목명/별칭 → 최신 요약·언급·신호 (예: 삼성전자, 하이닉스)\n"
                "· /브리핑 → 아침 브리핑 다시 받기\n"
                "· 문장으로 질문 → 수집 문서 근거로 AI 답변")

    if q in ("/브리핑", "브리핑"):
        from pipeline.notify import _compose_briefing
        return _compose_briefing() or "오늘 브리핑 내용이 없습니다."

    conn = get_connection()
    # 짧은 입력은 종목 조회 시도
    if len(q) <= 12 and " " not in q:
        ent = _find_company(conn, q)
        if ent:
            out = _stock_brief(conn, ent)
            conn.close()
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
            return "관련 수집 문서가 없어 답할 수 없습니다."
        parts = [r["answer"][:2500]]
        if r.get("gaps"):
            parts.append("\n⚠ " + " / ".join(g["note"][:60] for g in r["gaps"][:2]))
        parts.append(f"\n(출처 {len(r.get('citations', []))}건 · AI 종합 — 검증 필요)")
        return "\n".join(parts)

    return "찾지 못했습니다. 종목명 또는 문장형 질문을 보내주세요."


def _poll_loop():
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    offset = None
    while True:
        try:
            resp = requests.get(_api("getUpdates"),
                                params={"timeout": 50, "offset": offset}, timeout=60)
            for u in resp.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(chat_id):
                    continue  # 등록된 채팅만 (보안)
                text = msg.get("text", "")
                if not text:
                    continue
                if len(text) >= 15:  # 긴 질문은 시간이 걸림 — 선응답
                    _send(chat_id, "🔎 찾아보는 중…")
                _send(chat_id, handle_message(text))
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
    threading.Thread(target=_poll_loop, daemon=True, name="telegram-bot").start()
