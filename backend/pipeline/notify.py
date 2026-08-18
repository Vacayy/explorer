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

콘텐츠 v2(D-107, docs/specs/telegram-briefing.md): 어젯밤 미국장 + 어제의 주제(최다3+급상승2)
+ 팔로우 유튜브 3일치를 싣고, 주제·영상은 **inline keyboard 버튼**으로 낸다. 버튼을 누르면
`bot.py`의 콜백 핸들러가 기존 생성 로직(compute_narrative / 유튜브 lazy digest)을 그대로 돌려
결과를 다시 텔레그램으로 보낸다 — 브리핑을 읽는 것에서 **누르는 것**으로.
조립 자체는 LLM 0콜(전부 SQL + 이미 만들어진 캐시 읽기).
"""
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

from database import get_connection

KST = timezone(timedelta(hours=9))
JOB = "send_briefing"
SEND_RETRIES = 3          # 망 미연결(기상 직후 Wi-Fi 지연) 대비
SEND_BACKOFF = 5          # 초 — 5s, 10s
TOP_TOPICS = 3            # 어제 절대 최다 주제
SURGE_TOPICS = 2          # 점유율 급상승 주제 (최다와 중복 제거 후)
YOUTUBE_DAYS = 3          # 팔로우 유튜브 조회 기간
YOUTUBE_LIMIT = 6         # 버튼 수 상한 (메시지·키보드 비대화 방지)


def _us_section(lines: list[str]) -> None:
    """어젯밤 미국장 — 이미 만들어진 스냅샷·종합 캐시를 읽기만 한다 (LLM·네트워크 0).

    force=False 경로라 홈이 아직 종합을 안 만들었으면 synthesis=None — 그때는
    결정적 스켈레톤(쏠림·개별이슈)만 싣는다 (Partial 상태).
    """
    try:
        from pipeline.us_briefing import build_briefing
        b = build_briefing(force=False)
    except Exception:
        return
    if not b.get("movers"):
        return

    lines.append("")
    lines.append(f"🇺🇸 어젯밤 미국장 ({b.get('trade_date') or '-'})")
    syn = b.get("synthesis") or {}
    if syn.get("mood"):
        lines.append(syn["mood"])
    for c in (b.get("clusters") or [])[:2]:
        lines.append(f"  · 쏠림: {c['label']} {c['share_pct']}% "
                     f"({c['n']}종목, 중앙값 {c['median_change']:+.1f}%)")
    idio = b.get("idiosyncratic") or []
    if idio:
        lines.append("  · 이슈: " + " · ".join(
            f"{m['ticker']} {'/'.join(m['flags'])}" for m in idio[:3]))
    for sc in (syn.get("study_candidates") or [])[:2]:
        lines.append(f"  · 스터디: {sc}")


def _topics(conn) -> list[dict]:
    """어제의 주제 = 절대 최다 N + 점유율 급상승 M (D-107, 사용자 확정).

    최다만 쓰면 매일 같은 얼굴(AI·반도체·자동차)이고, 급상승만 쓰면 '어제 무엇이
    화두였나'에 답하지 않는다. 둘을 섞어 판의 크기와 변화를 함께 준다.
    문서유형 메타 라벨(산업동향·실적분석·수급…)은 제외 — 안 그러면 상위를 독식한다.
    """
    from pipeline.signals import THEME_STOPWORDS
    ph = ",".join("?" for _ in THEME_STOPWORDS)
    top = conn.execute(f"""
        SELECT e.id, e.name, count(DISTINCT rd.id) cnt
        FROM entity_links el
        JOIN entities e ON e.id = el.entity_id AND e.type IN ('theme','sector')
        JOIN raw_documents rd ON rd.id = el.doc_id
        WHERE el.link_type IN ('industry','topic')
          AND rd.published_at >= datetime('now','-1 day')
          AND e.name NOT IN ({ph})
        GROUP BY e.id ORDER BY cnt DESC LIMIT ?
    """, (*THEME_STOPWORDS, TOP_TOPICS)).fetchall()
    items = [{"id": r["id"], "name": r["name"], "kind": "top", "metric": f"{r['cnt']}"}
             for r in top]

    seen = {r["id"] for r in top}
    for r in conn.execute("""
        SELECT s.entity_id id, e.name, s.payload_json
        FROM signals s JOIN entities e ON e.id = s.entity_id
        WHERE s.signal_type='theme_surge'
          AND s.date = (SELECT max(date) FROM signals WHERE signal_type='theme_surge')
    """).fetchall():
        if r["id"] in seen:
            continue
        try:
            delta = json.loads(r["payload_json"] or "{}").get("share_delta_pp")
        except Exception:
            delta = None
        if delta is None:
            continue
        items.append({"id": r["id"], "name": r["name"], "kind": "surge",
                      "metric": f"+{delta}%p", "_sort": delta})
    surges = sorted([i for i in items if i["kind"] == "surge"],
                    key=lambda i: i["_sort"], reverse=True)[:SURGE_TOPICS]
    return [i for i in items if i["kind"] == "top"] + surges


def _youtube_recent(conn) -> list[dict]:
    """팔로우 채널의 최근 N일 영상 — source_id는 '{channel_id}/{video_id}' 규약."""
    return [dict(r) for r in conn.execute("""
        SELECT rd.id, rd.title, rd.digest_status,
               COALESCE(yc.title, '유튜브') channel
        FROM raw_documents rd
        LEFT JOIN youtube_channels yc
               ON yc.channel_id = substr(rd.source_id, 1, instr(rd.source_id, '/') - 1)
        WHERE rd.source_type='youtube'
          AND rd.published_at >= datetime('now', ?)
        ORDER BY rd.published_at DESC LIMIT ?
    """, (f"-{YOUTUBE_DAYS} days", YOUTUBE_LIMIT))]


def _keyboard(topics: list[dict], videos: list[dict]) -> dict | None:
    """inline keyboard — callback_data는 64바이트 상한이라 이름이 아닌 id를 싣는다."""
    rows = []
    for i in range(0, len(topics), 3):                       # 주제는 한 줄에 3개
        rows.append([{"text": f"🧠 {t['name']}", "callback_data": f"n:{t['id']}"}
                     for t in topics[i:i + 3]])
    for v in videos:                                          # 영상은 제목이 길어 한 줄에 1개
        label = f"📺 {v['channel']} — {v['title']}"
        rows.append([{"text": label[:56], "callback_data": f"y:{v['id']}"}])
    return {"inline_keyboard": rows} if rows else None


def compose_briefing() -> tuple[str, dict | None] | None:
    """브리핑 본문 + inline keyboard. 보낼 내용이 없으면 None.

    섹션은 서로 독립 — 하나가 비거나 실패해도 나머지는 실린다(Partial, D-107 §5).
    """
    from routers.spine_home import get_home
    home = get_home(days=1)

    lines = [f"📋 Explorer 아침 브리핑 — {datetime.now(KST).strftime('%m/%d %a')}"]

    if home.briefing:
        lines.append("")
        icon = {"insight": "💡", "action": "🏢", "signal": "📈",
                "warning": "⚠️", "conflict": "⚔️", "confirmed": "✅"}
        for b in home.briefing:
            lines.append(f"{icon.get(b.kind, '•')} {b.text}")

    _us_section(lines)

    conn = get_connection()
    try:
        topics = _topics(conn)
        videos = _youtube_recent(conn)
    finally:
        conn.close()

    if topics:
        lines.append("")
        lines.append("📊 어제의 주제")
        top = [t for t in topics if t["kind"] == "top"]
        surge = [t for t in topics if t["kind"] == "surge"]
        if top:
            lines.append("  [최다] " + " · ".join(f"{t['name']} {t['metric']}" for t in top))
        if surge:
            lines.append("  [급상승] " + " · ".join(f"{t['name']} {t['metric']}" for t in surge))

    if videos:
        lines.append("")
        lines.append(f"📺 팔로우 유튜브 최근 {YOUTUBE_DAYS}일 · {len(videos)}건")
        for v in videos:
            lines.append(f"  · {v['channel']} — {v['title'][:44]}")

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
    if topics or videos:
        lines.append("")
        lines.append("👇 눌러서 생성 — 결과를 이 대화로 보내드립니다")
    return "\n".join(lines), _keyboard(topics, videos)


def send_telegram(text: str, reply_markup: dict | None = None) -> bool:
    """발송 1건. 망 실패는 예외를 삼키지 않고 재시도 — 기상 직후 DNS 미해석으로
    스크립트가 죽어 그날 브리핑이 통째로 날아간 사례(2026-07-22) 방지."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    payload: dict = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    last = ""
    for attempt in range(SEND_RETRIES):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload, timeout=15,
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

    composed = compose_briefing()
    if not composed:
        return _done({"sent": False, "reason": "내용 없음"}, "skipped", "내용 없음")
    text, keyboard = composed
    n_btn = sum(len(r) for r in (keyboard or {}).get("inline_keyboard", []))
    if dry_run:
        print(text)
        print(f"\n[버튼 {n_btn}개] " + " / ".join(
            b["text"] for r in (keyboard or {}).get("inline_keyboard", []) for b in r))
        return {"sent": False, "reason": "dry-run", "chars": len(text), "buttons": n_btn}
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return _done({"sent": False, "reason": "TELEGRAM_BOT_TOKEN 미설정 (.env)"},
                     "skipped", "TELEGRAM_BOT_TOKEN 미설정")
    if send_telegram(text, keyboard):
        return _done({"sent": True, "chars": len(text), "buttons": n_btn},
                     "ok", f"{len(text)}자 · 버튼 {n_btn}개 발송")
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
