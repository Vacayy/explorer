"""브리핑 push — 텔레그램 봇으로 아침 브리핑 발송 (도구 밖에서 열람을 당긴다).

셋업 (1회):
  1. 텔레그램 @BotFather → /newbot → 토큰 발급
  2. 만든 봇에게 아무 메시지 전송 후
     https://api.telegram.org/bot<토큰>/getUpdates 에서 chat.id 확인
  3. .env에 TELEGRAM_BOT_TOKEN=..., TELEGRAM_CHAT_ID=...
미설정 시 조용히 skip (cron 안전).
"""
import os
from datetime import date, datetime, timedelta, timezone

import requests

from database import get_connection

KST = timezone(timedelta(hours=9))


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
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text}, timeout=15,
    )
    return resp.status_code == 200


def push_briefing(dry_run: bool = False) -> dict:
    text = _compose_briefing()
    if not text:
        return {"sent": False, "reason": "내용 없음"}
    if dry_run:
        print(text)
        return {"sent": False, "reason": "dry-run", "chars": len(text)}
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return {"sent": False, "reason": "TELEGRAM_BOT_TOKEN 미설정 (.env)"}
    ok = send_telegram(text)
    return {"sent": ok, "chars": len(text)}
