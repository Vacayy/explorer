"""브리핑 push — 텔레그램 봇으로 아침 브리핑 발송 (도구 밖에서 열람을 당긴다).

셋업 (1회):
  1. 텔레그램 @BotFather → /newbot → 토큰 발급
  2. 만든 봇에게 아무 메시지 전송 후
     https://api.telegram.org/bot<토큰>/getUpdates 에서 chat.id 확인
  3. .env에 TELEGRAM_BOT_TOKEN=..., TELEGRAM_CHAT_ID=...
미설정 시 조용히 skip (스케줄러 안전).

발송 보장(D-106): 스케줄러가 08:00에 못 뜨거나(랩탑 수면) 그 순간 망이 안 붙어도
그날 브리핑이 증발하지 않도록 ①모든 시도를 job_runs에 기록하고 ②30분 체인이
`ensure_briefing_sent()`로 미발송을 사후 보전한다.
"""
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

from database import get_connection

KST = timezone(timedelta(hours=9))
JOB = "send_briefing"
SEND_RETRIES = 3          # 망 미연결(기상 직후 Wi-Fi 지연) 대비
SEND_BACKOFF = 5          # 초 — 5s, 10s


def _compose_briefing() -> str | None:
    """홈 브리핑과 같은 재료로 텔레그램용 텍스트 구성 (링크는 로컬이라 텍스트 중심)."""
    from routers.spine_home import get_home
    home = get_home(days=1)

    lines = [f"📋 Explorer 아침 브리핑 — {datetime.now(KST).strftime('%m/%d %a')}"]

    if home.briefing:
        lines.append("")
        icon = {"insight": "💡", "action": "🏢", "signal": "📈", "warning": "⚠️"}
        for b in home.briefing:
            lines.append(f"{icon.get(b.kind, '•')} {b.text}")

    today = date.today().isoformat()
    todays = [e for e in home.calendar if e.event_date == today]
    if todays:
        lines.append("")
        lines.append("📅 오늘 일정")
        for e in todays[:5]:
            corp = f" ({e.corp_name})" if e.corp_name else ""
            lines.append(f"  · {e.title}{corp}")

    n_updates = len(home.watchlist_updates)
    if n_updates:
        lines.append("")
        lines.append(f"🔔 내 종목·팔로우 업데이트 {n_updates}건 — 홈에서 확인")

    if len(lines) <= 1:
        return None  # 보낼 내용 없음
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    """발송 1건. 망 실패는 예외를 삼키지 않고 재시도 — 기상 직후 DNS 미해석으로
    스크립트가 죽어 그날 브리핑이 통째로 날아간 사례(2026-07-22) 방지."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    last = ""
    for attempt in range(SEND_RETRIES):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text}, timeout=15,
            )
            if resp.status_code == 200:
                return True
            last = f"HTTP {resp.status_code}"
        except Exception as e:  # noqa: BLE001 — 망 미연결도 재시도 대상
            last = f"{type(e).__name__}"
        if attempt < SEND_RETRIES - 1:
            time.sleep(SEND_BACKOFF * (attempt + 1))
    print(f"[send_telegram] {SEND_RETRIES}회 실패 — {last}", flush=True)
    return False


def _attempted_today(conn) -> bool:
    """오늘(KST) 발송을 이미 시도했나 — ok/skipped는 완료로 본다(error만 재시도 대상).

    '내용 없음'을 미시도로 보면 하루 종일 재시도하다 늦은 시각에 툭 발송될 수 있어,
    시도 자체를 하루 1회로 못박는다.
    """
    today = datetime.now(KST).date().isoformat()
    row = conn.execute(
        "SELECT 1 FROM job_runs WHERE job=? AND status IN ('ok','skipped') "
        "AND date(ran_at, '+9 hours') = ? LIMIT 1", (JOB, today)).fetchone()
    return row is not None


def push_briefing(dry_run: bool = False) -> dict:
    """브리핑 1회 발송 + 결과를 job_runs에 기록(관리자 페이지·캐치업 판정의 근거)."""
    from pipeline.ops import record_run
    t0 = time.time()

    def _done(result: dict, status: str, summary: str) -> dict:
        if not dry_run:
            record_run(JOB, status, summary, int((time.time() - t0) * 1000))
        return result

    text = _compose_briefing()
    if not text:
        return _done({"sent": False, "reason": "내용 없음"}, "skipped", "내용 없음")
    if dry_run:
        print(text)
        return {"sent": False, "reason": "dry-run", "chars": len(text)}
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return _done({"sent": False, "reason": "TELEGRAM_BOT_TOKEN 미설정 (.env)"},
                     "skipped", "TELEGRAM_BOT_TOKEN 미설정")
    if send_telegram(text):
        return _done({"sent": True, "chars": len(text)}, "ok", f"{len(text)}자 발송")
    return _done({"sent": False, "reason": "발송 실패"}, "error", "텔레그램 발송 실패")


def ensure_briefing_sent() -> dict:
    """미발송 사후 보전 — 30분 체인이 매 회차 호출(멱등).

    평일 08:00(KST)이 지났는데 오늘 시도 기록이 없으면 지금 발송한다.
    launchd가 기상 시 놓친 회차를 실행하지만, 전원이 꺼져 있었거나 발송이
    망 실패로 error가 난 경우까지 덮는 마지막 그물.
    """
    now = datetime.now(KST)
    if now.weekday() > 4:
        return {"sent": False, "reason": "주말"}
    if now.hour < 8:
        return {"sent": False, "reason": "08:00 이전"}
    conn = get_connection()
    try:
        if _attempted_today(conn):
            return {"sent": False, "reason": "오늘 발송 완료"}
    finally:
        conn.close()
    r = push_briefing()
    r["catch_up"] = True
    return r
