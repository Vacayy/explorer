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
+ 팔로우 유튜브 3일치. 조립 자체는 LLM 0콜(전부 SQL + 이미 만들어진 캐시 읽기).

v3(D-109): 본문을 **HTML(parse_mode)** 로 보내고, 액션을 하단 버튼이 아니라 **본문 인라인
하이퍼링크**로 심는다. 텔레그램 인라인 링크는 URL만 걸 수 있어 콜백을 못 쓰므로,
`https://t.me/<bot>?start=<payload>` **딥링크**로 봇에게 `/start n_4740`을 되돌려준다
(bot.py가 콜백과 같은 핸들러로 라우팅). 마크다운→HTML 변환·분할은 pipeline/telegram_md.py.
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
YOUTUBE_LIMIT = 6         # 목록 상한 (메시지 비대화 방지)

_bot_username: str | None = None


def bot_username() -> str | None:
    """딥링크에 쓸 봇 핸들. .env 오버라이드 우선, 없으면 getMe 1회 조회 후 캐시."""
    global _bot_username
    if _bot_username is None:
        _bot_username = (os.getenv("TELEGRAM_BOT_USERNAME") or "").lstrip("@").strip()
    if _bot_username:
        return _bot_username
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
        if r.get("ok"):
            _bot_username = r["result"]["username"]
    except Exception:  # noqa: BLE001 — 링크 없이 평문으로 나가면 될 뿐, 발송을 막지 않는다
        return None
    return _bot_username or None


def action_link(label: str, kind: str, ident: int) -> str:
    """본문 인라인 액션 링크. 봇 핸들을 못 구하면 링크 없이 라벨만(평문 열화).

    payload는 `A-Za-z0-9_-` 64자 제한이라 `n:4740`이 아니라 `n_4740`을 쓴다.
    """
    from pipeline.telegram_md import esc, link
    user = bot_username()
    if not user:
        return esc(label)
    return link(label, f"https://t.me/{user}?start={kind}_{ident}")


def _us_section(lines: list[str]) -> None:
    """어젯밤 미국장 — 이미 만들어진 스냅샷·종합 캐시를 읽기만 한다 (LLM·네트워크 0).

    4섹션 종합(D-112: 지수·요인·이슈·흐름)을 소제목과 함께 싣는다. force=False 경로라
    아직 종합이 없으면 결정적 스켈레톤(쏠림·개별이슈)만 나간다 (Partial 상태).
    """
    from pipeline.telegram_md import esc
    try:
        from pipeline.us_briefing import build_briefing
        b = build_briefing(force=False)
    except Exception:
        return
    if not b.get("movers"):
        return

    lines.append("")
    lines.append(f"🇺🇸 <b>어젯밤 미국장</b> ({esc(b.get('trade_date') or '-')})")

    # '어젯밤'을 자처하는데 며칠 묵었으면 먼저 밝힌다 — 날짜만 찍고 넘어가면 프레임이 거짓이 된다
    stale = b.get("stale_days")
    if stale and stale > 1:
        lines.append(f"  ⚠️ <i>스냅샷이 {stale}일 전 것입니다 (자동 갱신 실패 의심)</i>")

    syn = b.get("synthesis") or {}
    for key, label in (("index_summary", "지수 마감"), ("drivers", "움직인 요인"),
                       ("issues", "거래대금 이슈"), ("flow", "시계열 흐름")):
        if syn.get(key):
            lines.append("")
            lines.append(f"  <b>{label}</b>")
            lines.append(f"  {esc(syn[key])}")

    # 지수 수치는 ① 산문이 이미 담는다(D-113 형식) — 여기서 반복하지 않는다.
    # 산문에 없는 수치 근거만 짧게 붙인다.
    lines.append("")
    for c in (b.get("clusters") or [])[:2]:
        lines.append(f"  · 쏠림: <b>{esc(c['label'])}</b> {c['share_pct']}% "
                     f"({c['n']}종목, 중앙값 {c['median_change']:+.1f}%)")
    idio = b.get("idiosyncratic") or []
    if idio:
        lines.append("  · 이슈: " + " · ".join(
            f"{esc(m['ticker'])} {esc('/'.join(m['flags']))}" for m in idio[:3]))
    sectors = (b.get("flow") or {}).get("sectors") or []
    if sectors:
        lines.append("  · 국면: " + " · ".join(
            f"{esc(x['label'])} {esc((x.get('trend') or {}).get('label') or '')}"
            for x in sectors[:3]))
    for sc in (syn.get("study_candidates") or [])[:2]:
        lines.append(f"  · 스터디: {esc(sc)}")


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
        SELECT rd.id, rd.title, rd.url, rd.digest_status,
               COALESCE(yc.title, '유튜브') channel
        FROM raw_documents rd
        LEFT JOIN youtube_channels yc
               ON yc.channel_id = substr(rd.source_id, 1, instr(rd.source_id, '/') - 1)
        WHERE rd.source_type='youtube'
          AND rd.published_at >= datetime('now', ?)
        ORDER BY rd.published_at DESC LIMIT ?
    """, (f"-{YOUTUBE_DAYS} days", YOUTUBE_LIMIT))]


def compose_briefing() -> str | None:
    """브리핑 본문(HTML). 보낼 내용이 없으면 None.

    섹션은 서로 독립 — 하나가 비거나 실패해도 나머지는 실린다(Partial, D-107 §5).
    액션은 본문 인라인 딥링크로 심는다(D-109) — 하단 버튼 행 없음.
    """
    from routers.spine_home import get_home
    from pipeline.telegram_md import esc, link
    home = get_home(days=1)

    lines = [f"📋 <b>Explorer 아침 브리핑</b> — {datetime.now(KST).strftime('%m/%d %a')}"]

    # 홈의 '기계의 3줄'은 싣지 않는다 (D-111) — 소스 경고·공시 접수·저점유 주제 같은
    # 낮은 신호가 브리핑 최상단을 차지해 정작 읽을 것(미국장·주제·유튜브)을 밀어냈다.
    # 다만 LLM 엔진 다운은 '아래 내용 전체가 열화됐다'는 메타 경보라 예외로 남긴다(D-106).
    from pipeline.ops import llm_down_reason
    llm_down = llm_down_reason()
    if llm_down:
        lines.append("")
        lines.append(f"⚠️ <b>LLM 엔진 응답 실패</b> — 아래 내용이 열화됐을 수 있습니다 "
                     f"({esc(llm_down)})")

    _us_section(lines)

    conn = get_connection()
    try:
        topics = _topics(conn)
        videos = _youtube_recent(conn)
    finally:
        conn.close()

    def _topic_line(label: str, items: list[dict]) -> str:
        # 주제명 자체가 링크 — 누르면 내러티브 생성이 걸린다
        return f"  [{label}] " + " · ".join(
            f"{action_link(t['name'], 'n', t['id'])} <i>{esc(t['metric'])}</i>" for t in items)

    if topics:
        lines.append("")
        lines.append("📊 <b>어제의 주제</b>")
        top = [t for t in topics if t["kind"] == "top"]
        surge = [t for t in topics if t["kind"] == "surge"]
        if top:
            lines.append(_topic_line("최다", top))
        if surge:
            lines.append(_topic_line("급상승", surge))

    if videos:
        lines.append("")
        lines.append(f"📺 <b>팔로우 유튜브</b> 최근 {YOUTUBE_DAYS}일 · {len(videos)}건")
        for v in videos:
            title = v["title"][:52]
            head = link(title, v["url"]) if v["url"] else esc(title)   # 제목=유튜브 원문
            lines.append(f"  · {esc(v['channel'])} — {head}")
            # 이미 만들어져 있으면 '생성'이 아니라 '보기' — 워딩이 상태를 드러내게 (D-111)
            verb = "▸ 정리본 보기" if v["digest_status"] == "ok" else "▸ 정리본 생성"
            lines.append(f"    {action_link(verb, 'y', v['id'])}")

    today = date.today().isoformat()
    todays = [e for e in home.calendar if e.event_date == today]
    if todays:
        lines.append("")
        lines.append("📅 <b>오늘 일정</b>")
        for e in todays[:5]:
            corp = f" ({esc(e.corp_name)})" if e.corp_name else ""
            lines.append(f"  · {esc(e.title)}{corp}")

    n_updates = len(home.watchlist_updates)
    if n_updates:
        lines.append("")
        lines.append(f"🔔 내 종목·팔로우 업데이트 {n_updates}건 — 홈에서 확인")

    if len(lines) <= 1:
        return None  # 보낼 내용 없음
    if (topics or videos) and bot_username():
        lines.append("")
        lines.append("<i>링크를 누르면 결과가 이 대화로 옵니다.</i>")
    return "\n".join(lines)


def send_telegram(text: str, parse_mode: str | None = "HTML") -> bool:
    """발송. 상한 초과분은 태그 경계를 지켜 나눠 보낸다(D-109).

    망 실패는 예외를 삼키지 않고 재시도 — 기상 직후 DNS 미해석으로 스크립트가 죽어
    그날 브리핑이 통째로 날아간 사례(2026-07-22) 방지.
    """
    from pipeline.telegram_md import split_html
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    parts = split_html(text) if parse_mode == "HTML" else [text]
    return all(_send_one(token, chat_id, p, parse_mode) for p in parts)


def _send_one(token: str, chat_id: str, text: str, parse_mode: str | None) -> bool:
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    last = ""
    for attempt in range(SEND_RETRIES):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload, timeout=15,
            )
            if resp.status_code == 200:
                return True
            # 400은 대개 마크업 파싱 실패 — 재시도해도 같으니 평문으로 1회 구제.
            # 링크·굵기를 잃더라도 내용이 유실되는 것보다 낫다.
            last = f"HTTP {resp.status_code} {resp.text[:160]}"
            if resp.status_code == 400 and parse_mode:
                print(f"[send_telegram] 마크업 파싱 실패 → 평문 재시도: {last}", flush=True)
                return _send_one(token, chat_id, _strip_tags(text), None)
        except Exception as e:  # noqa: BLE001 — 망 미연결도 재시도 대상
            last = f"{type(e).__name__}"
        if attempt < SEND_RETRIES - 1:
            time.sleep(SEND_BACKOFF * (attempt + 1))
    print(f"[send_telegram] {SEND_RETRIES}회 실패 — {last}", flush=True)
    return False


def _strip_tags(text: str) -> str:
    import html as _html
    import re as _re
    return _html.unescape(_re.sub(r"<[^>]+>", "", text))


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

    text = compose_briefing()
    if not text:
        return _done({"sent": False, "reason": "내용 없음"}, "skipped", "내용 없음")
    n_link = text.count("?start=")
    if dry_run:
        print(text)
        print(f"\n[액션 링크 {n_link}개]")
        return {"sent": False, "reason": "dry-run", "chars": len(text), "links": n_link}
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return _done({"sent": False, "reason": "TELEGRAM_BOT_TOKEN 미설정 (.env)"},
                     "skipped", "TELEGRAM_BOT_TOKEN 미설정")
    if send_telegram(text):
        return _done({"sent": True, "chars": len(text), "links": n_link},
                     "ok", f"{len(text)}자 · 액션 링크 {n_link}개 발송")
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
