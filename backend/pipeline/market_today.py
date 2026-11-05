"""Market Today — 오늘 장중 실시간 소스 화두 요약 (docs/specs/market-today.md).

평일 네 회차(09:30·11:30·15:00 장중 + 16:00 마감 정리, KST, 2026-11-05 변경)마다 직전 창의 텔레그램 글과 지정 매체
헤드라인(macro_news)을 모아 **지금 주로 나오는 얘기** 3~5개를 sonnet 1콜로 묶는다. 마감 정리는 직전 창이 아니라
그날 장 전체(09:00~16:00)를 보고 오늘 하루를 정리한다. 화두마다 출처 원문에서 글자 그대로 복사한 인용을
받아 원문에서 확인된 것만 채택한다(미국장 브리핑 매크로 이슈와 같은 규율, us_briefing._verify_issues).
화두 순서는 LLM이 아니라 **언급한 출처 수**로 정한다 — 회차마다 기준이 흔들리지 않게.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from database import get_connection
from pipeline.enrich import _call_claude_code, _parse_json, llm_engine
from pipeline.us_briefing import _QUOTE_MIN, _norm_quote
from pipeline.visibility import UNVERIFIED_SOURCES

KST = ZoneInfo("Asia/Seoul")
SLOTS = [("0930", dtime(9, 30)), ("1130", dtime(11, 30)), ("1500", dtime(15, 0)), ("1600", dtime(16, 0))]
WRAP_SLOT = "1600"                 # 마감 정리 — 오늘 하루 전체 창
DAY_OPEN = dtime(9, 0)
# 옛 회차(11-05 전 10:00·13:00·15:40)도 읽을 수 있게 라벨은 남긴다
SLOT_LABEL = {"0930": "09:30", "1130": "11:30", "1500": "15:00", "1600": "16:00 마감",
              "1000": "10:00", "1300": "13:00", "1540": "15:40"}
MAX_DOCS = 80          # 프롬프트 입력 상한(묶음 기준)
MAX_TELEGRAM = 50      # 그중 텔레그램 몫 — 나머지는 지정 매체 헤드라인
DOC_CHARS = 600        # 텔레그램 글 발췌 길이 — 인용 검증 대상도 이 범위
MAX_TOPICS = 5
MIN_DOCS = 5           # 창 안 자료가 이보다 적으면 만들지 않는다(skipped)
MODEL = "sonnet"

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_today (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date    TEXT NOT NULL,          -- KST 거래일
    slot          TEXT NOT NULL,          -- 0930 | 1130 | 1500 | 1600(마감 정리) · 옛 1000 | 1300 | 1540
    window_start  TEXT NOT NULL,          -- UTC ISO
    window_end    TEXT NOT NULL,
    items_json    TEXT NOT NULL,          -- [{title, body, tags, refs, continuing}]
    sources_json  TEXT NOT NULL,          -- ref → {kind, publisher, title, url, doc_id, published_at}
    doc_count     INTEGER NOT NULL,       -- 창 안 자료 수(묶기 전)
    counts_json   TEXT,                   -- {telegram, news}
    market_json   TEXT,                   -- 회차 시점 시장 상태 {kospi, kosdaq: {value, change_pct, at}, path: [[HH:MM, 코스피]]}
    model         TEXT,
    created_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(trade_date, slot)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    try:  # 2026-11-03 추가 컬럼 — 회차 시점 시장 상태
        conn.execute("ALTER TABLE market_today ADD COLUMN market_json TEXT")
    except Exception:  # noqa: BLE001 — 이미 있으면 그대로
        pass


INDEX_TICKERS = {"kospi": "^KS11", "kosdaq": "^KQ11"}


def market_snapshot(day: date, slot: str) -> dict | None:
    """회차 시점의 코스피·코스닥 값과 전일 대비, 그 시각까지의 코스피 5분 경로 — 화두가 돌 때 시장이 어땠는지 나중에 맞대 보려고 쌓는다.

    yfinance 장중 5분봉은 마지막 30분가량이 늦게 들어오므로 장 마감 회차(16:00)는 당일 종가가 있으면 그것을 쓴다.
    실패하면 None — 화두 생성은 막지 않는다.
    """
    try:
        import yfinance as yf
        slot_t = dict(SLOTS).get(slot) or dtime(int(slot[:2]), int(slot[2:]))
        out, path = {}, []
        for key, tk in INDEX_TICKERS.items():
            t = yf.Ticker(tk)
            daily = t.history(period="10d")["Close"]
            prev = [v for idx, v in daily.items() if idx.date() < day]
            close_today = next((v for idx, v in daily.items() if idx.date() == day), None)
            bars = [(idx.astimezone(KST), v) for idx, v in t.history(period="5d", interval="5m")["Close"].items()
                    if idx.astimezone(KST).date() == day and idx.astimezone(KST).time() <= slot_t]
            if slot_t >= dtime(15, 30) and close_today is not None:
                value, at = float(close_today), "15:30"
            elif bars:
                value, at = float(bars[-1][1]), bars[-1][0].strftime("%H:%M")
            else:
                continue
            base = float(prev[-1]) if prev else None
            out[key] = {"value": round(value, 2), "change_pct": round((value / base - 1) * 100, 2) if base else None, "at": at}
            if key == "kospi":
                path = [[ts.strftime("%H:%M"), round(float(v), 2)] for ts, v in bars]
        return {**out, "path": path} if out else None
    except Exception as e:  # noqa: BLE001
        print(f"[market_today] 시장 상태 조회 실패: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return None


# ---------- 시점 ----------

def _kst(day: date, t: dtime) -> datetime:
    return datetime.combine(day, t, KST)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def due_slot(now: datetime | None = None) -> tuple[date, str] | None:
    """지금 시점에 가장 최근에 지난 회차 (주말이면 None). 따라잡기는 launchd CATCHUP 창(2시간)이 자른다."""
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    if now.weekday() >= 5:
        return None
    passed = [s for s, t in SLOTS if now.time() >= t]
    return (now.date(), passed[-1]) if passed else None


def is_trading_day(day: date) -> tuple[bool, str]:
    """국장 개장일인가 — 코스피 당일 봉이 있으면 개장. yfinance 실패 시 평일 규칙으로 대신한다(사유를 돌려준다)."""
    if day.weekday() >= 5:
        return False, "주말"
    try:
        import yfinance as yf
        hist = yf.Ticker("^KS11").history(period="5d")
        days = {idx.date() for idx in hist.index}
        if not days:
            return True, "코스피 시세 없음 — 평일 규칙"
        return (day in days), ("코스피 당일 봉 있음" if day in days else "코스피 당일 봉 없음(휴장)")
    except Exception as e:  # noqa: BLE001 — 판정 실패로 회차를 잃지 않는다
        return True, f"휴장 판정 실패({type(e).__name__}) — 평일 규칙"


def _prev_trading_day(conn, day: date) -> date:
    row = conn.execute("SELECT MAX(trade_date) d FROM stock_prices WHERE trade_date < ?", (day.isoformat(),)).fetchone()
    if row and row["d"]:
        return max(date.fromisoformat(row["d"][:10]), day - timedelta(days=5))
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def window(conn, day: date, slot: str) -> tuple[str, str]:
    """[start, end) UTC. 첫 회차는 전 거래일 마감 정리(16:00)부터(밤사이 미국장·해외 뉴스 포함), 장중 회차는 직전 회차부터,
    마감 정리는 그날 09:00부터(오늘 하루 전체)."""
    keys = [s for s, _ in SLOTS]
    i = keys.index(slot)
    end = _kst(day, SLOTS[i][1])
    if slot == WRAP_SLOT:
        start = _kst(day, DAY_OPEN)
    elif i == 0:
        start = _kst(_prev_trading_day(conn, day), SLOTS[-1][1])
    else:
        start = _kst(day, SLOTS[i - 1][1])
    return _utc(start), _utc(end)


# ---------- 원천 ----------

def _norm_title(text: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\(\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}.*?\)|https?://\S+", " ", text or "")
    t = re.sub(r"[^0-9A-Za-z가-힣]+", "", t).lower()
    return t[:40]


def gather(conn, start: str, end: str) -> tuple[list[dict], dict]:
    """창 안의 자료를 같은 얘기끼리 묶어 출처 목록으로. 묶음 크기(언급한 출처 수) 큰 순, 상한 MAX_DOCS."""
    from pipeline.macro_news import read_window
    if "telegram" in UNVERIFIED_SOURCES:   # 방어 — 텔레그램이 미검증으로 바뀌면 이 기능은 성립하지 않는다
        return [], {"telegram": 0, "news": 0}
    rows = conn.execute(
        "SELECT rd.id, rd.title, rd.url, rd.published_at, rd.markdown, "
        "       COALESCE(tc.display_name, tc.channel_name, substr(rd.source_id, 1, instr(rd.source_id, '/') - 1)) publisher "
        "FROM raw_documents rd LEFT JOIN telegram_channels tc ON rd.source_id LIKE tc.channel_name || '/%' "
        "WHERE rd.source_type='telegram' AND rd.published_at >= ? AND rd.published_at < ? "
        "  AND length(COALESCE(rd.markdown, '')) >= 20 ORDER BY rd.published_at", (start, end)).fetchall()
    items = [{"kind": "telegram", "publisher": r["publisher"] or "텔레그램", "title": (r["title"] or "")[:140],
              "url": r["url"], "doc_id": r["id"], "published_at": r["published_at"],
              "text": (r["markdown"] or "")[:DOC_CHARS]} for r in rows]
    news = read_window(conn, start, end)
    items += [{"kind": "news", "publisher": n["publisher"], "title": n["title"], "url": n["url"], "doc_id": None,
               "published_at": n["published_at"], "text": n["title"] + ("\n" + n["summary"] if n.get("summary") else "")}
              for n in news]
    counts = {"telegram": len(rows), "news": len(news)}
    groups: dict[str, list[dict]] = {}
    for it in items:
        key = _norm_title(it["title"]) or _norm_title(it["text"][:80])
        if len(key) < 6:          # 날짜만 있는 제목('2026.11.03 15:51:58') 같은 것은 본문으로 묶는다
            key = _norm_title(it["text"][:120]) or f"doc{id(it)}"
        groups.setdefault(key, []).append(it)
    out = []
    for g in groups.values():
        head = g[0]
        publishers = sorted({x["publisher"] for x in g})
        out.append({**head, "echo": len(publishers), "publishers": publishers})
    # 같은 얘기를 다룬 출처가 많은 것부터, 같으면 최신부터. 밤사이 해외 헤드라인이 국내 채널 화두를 밀어내지 않게 몫을 나눈다
    out.sort(key=lambda x: (x["echo"], x["published_at"] or ""), reverse=True)
    tg = [x for x in out if x["kind"] == "telegram"][:MAX_TELEGRAM]
    nw = [x for x in out if x["kind"] != "telegram"][:MAX_DOCS - len(tg)]
    out = sorted(tg + nw, key=lambda x: (x["echo"], x["published_at"] or ""), reverse=True)
    for i, s in enumerate(out, 1):
        s["ref"] = f"S{i}"
    return out, counts


# ---------- 생성 ----------

def _prompt(day: date, slot: str, sources: list[dict], prev_titles: list[str]) -> str:
    def fmt(s):
        echo = f" · 같은 얘기 {s['echo']}곳" if s["echo"] > 1 else ""
        when = (s["published_at"] or "")[:16]
        return f"<{s['ref']} | {s['kind']} | {s['publisher']}{echo} | {when}Z>\n{s['text'].strip()}\n</{s['ref']}>"
    prev = "\n".join(f"- {t}" for t in prev_titles) or "(없음 — 오늘 첫 회차)"
    if slot == WRAP_SLOT:
        head = (f"당신은 국내 증시 데스크 기자다. {day.isoformat()} 장이 끝났다. 오늘 장중(09:00~16:00) 텔레그램 채널과 "
                "주요 매체에서 **오늘 하루 주로 나온 얘기** 3~5개로 오늘 장을 정리한다. 장중 회차 화두를 되풀이하기보다 "
                "하루를 통틀어 가장 많이 다뤄졌고 시장에 영향이 컸던 얘기를 고른다. 리서치를 대신하지 않는다.\n\n")
        prev_head = "[오늘 장중 회차 화두]"
    else:
        head = (f"당신은 국내 증시 데스크 기자다. {day.isoformat()} {SLOT_LABEL[slot]} 기준으로, 직전 창에 텔레그램 채널과 "
                "주요 매체에서 **주로 나온 얘기** 3~5개를 묶는다. 리서치를 대신하지 않고, 지금 무엇이 화두인지 알려 주는 것이 목적이다.\n\n")
        prev_head = "[직전 회차 화두]"
    return (
        head +
        "규칙:\n"
        "- 화두는 여러 출처가 다룬 것, 시장(지수·업종·금리·환율·원자재)에 영향을 줄 만한 것을 우선한다. "
        "같은 얘기 N곳 표시는 여러 채널이 다룬 정도다. 한 채널의 의견을 시장의 합의로 부풀리지 않는다.\n"
        "- 투자와 무관한 잡담·광고·채널 공지·날짜만 있는 글은 버린다.\n"
        "- title: 한 줄 명사구, 25자 이내(예: '미국, 이란 케슘섬 공습').\n"
        "- body: 1~2문장, 존댓말(합니다체를 뼈대로 하되 해요체를 한 번 섞어도 된다). 누가 무엇을 말했는지와 "
        "시장이 어떻게 읽는지를 출처에 있는 그대로. 출처에 없는 수치·인과를 보태지 않는다. 매매 처방 금지.\n"
        "- tags: 2~3개 짧은 주제어.\n"
        "- continuing: 위 화두 목록의 얘기와 같은 얘기가 이어지면 true.\n"
        "- sources: 근거 출처 1~3개. quote는 해당 출처 원문에서 **글자 그대로 복사한** 연속 구간(10~120자). "
        "번역·요약·말줄임 금지. 한 글자라도 다르면 그 출처는 버려지고, 출처가 하나도 안 남은 화두는 버려진다.\n"
        "- 화두가 없으면 빈 배열. 지어내지 마라.\n\n"
        f"{prev_head}\n{prev}\n\n"
        f"[자료]\n" + "\n\n".join(fmt(s) for s in sources) + "\n\n"
        "JSON만 출력: {\"topics\": [{\"title\": \"…\", \"body\": \"…\", \"tags\": [\"…\"], \"continuing\": false, "
        "\"sources\": [{\"ref\": \"S3\", \"quote\": \"원문 그대로\"}]}]}"
    )


def verify(raw, sources: list[dict]) -> list[dict]:
    """인용이 원문에 그대로 있는 출처만 채택. 출처가 남지 않은 화두는 버린다. 순서 = 언급 출처 수(묶음 포함) 큰 순."""
    by_ref = {s["ref"]: s for s in sources}
    out = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict) or not str(it.get("title") or "").strip():
            continue
        refs = []
        for c in it.get("sources") or []:
            if not isinstance(c, dict):
                continue
            src = by_ref.get(str(c.get("ref") or "").strip())
            q = _norm_quote(c.get("quote")).strip("\"' ")
            if src and len(q) >= _QUOTE_MIN and q in _norm_quote(src["text"]) and src["ref"] not in refs:
                refs.append(src["ref"])
        if not refs:
            continue
        pubs = {p for r in refs for p in by_ref[r]["publishers"]}
        out.append({"title": str(it["title"]).strip()[:40], "body": str(it.get("body") or "").strip()[:300],
                    "tags": [str(t)[:12] for t in (it.get("tags") or [])[:3] if str(t).strip()],
                    "continuing": bool(it.get("continuing")), "refs": refs, "echo": len(pubs)})
    out.sort(key=lambda x: -x["echo"])
    return out[:MAX_TOPICS]


def run(day: date | None = None, slot: str | None = None, force: bool = False, call=None, check_holiday=True,
        snapshot=None) -> dict:
    """한 회차를 만든다. 반환 {status: ok|skipped|exists|error, ...}. call·snapshot은 테스트용 대역(LLM·시세)."""
    if day is None or slot is None:
        due = due_slot()
        if not due:
            return {"status": "skipped", "reason": "주말이거나 첫 회차(09:30) 전"}
        day, slot = due
    if slot not in SLOT_LABEL:
        return {"status": "error", "reason": f"알 수 없는 회차 {slot}"}
    if check_holiday:
        open_, why = is_trading_day(day)
        if not open_:
            return {"status": "skipped", "reason": why}
    conn = get_connection()
    try:
        ensure_schema(conn)
        if not force and conn.execute("SELECT 1 FROM market_today WHERE trade_date=? AND slot=?",
                                      (day.isoformat(), slot)).fetchone():
            return {"status": "exists", "trade_date": day.isoformat(), "slot": slot}
        start, end = window(conn, day, slot)
        sources, counts = gather(conn, start, end)
        if sum(counts.values()) < MIN_DOCS:
            return {"status": "skipped", "reason": f"창 안 자료 {sum(counts.values())}건", **counts}
        if call is None and llm_engine() != "claude-code":
            return {"status": "error", "reason": "LLM 미가용"}
        prev_rows = conn.execute("SELECT items_json FROM market_today WHERE trade_date=? AND slot<? ORDER BY slot DESC",
                                 (day.isoformat(), slot)).fetchall()
        if slot != WRAP_SLOT:          # 장중 회차는 직전 회차만, 마감 정리는 그날 장중 회차 전부
            prev_rows = prev_rows[:1]
        prev_titles = list(dict.fromkeys(t["title"] for r in prev_rows for t in json.loads(r["items_json"])))
        prompt = _prompt(day, slot, sources, prev_titles)
        try:
            raw = (call or (lambda p: _call_claude_code(p, model=MODEL, timeout=300)))(prompt)
            data = _parse_json(raw) if isinstance(raw, str) else raw
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "reason": f"생성 실패: {type(e).__name__}: {str(e)[:160]}"}
        topics = verify((data or {}).get("topics") if isinstance(data, dict) else None, sources)
        used = {r for t in topics for r in t["refs"]}
        meta = {s["ref"]: {k: s[k] for k in ("kind", "publisher", "title", "url", "doc_id", "published_at")} | {"echo": s["echo"]}
                for s in sources if s["ref"] in used}
        market = (snapshot or market_snapshot)(day, slot)
        conn.execute(
            "INSERT OR REPLACE INTO market_today (trade_date, slot, window_start, window_end, items_json, sources_json, "
            "doc_count, counts_json, market_json, model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))",
            (day.isoformat(), slot, start, end, json.dumps(topics, ensure_ascii=False), json.dumps(meta, ensure_ascii=False),
             sum(counts.values()), json.dumps(counts), json.dumps(market) if market else None, MODEL))
        conn.commit()
        return {"status": "ok", "trade_date": day.isoformat(), "slot": slot, "topics": len(topics),
                "dropped": len(((data or {}).get("topics") or [])) - len(topics) if isinstance(data, dict) else 0, **counts}
    finally:
        conn.close()


# ---------- 읽기 ----------

def read(day: str | None = None, slot: str | None = None) -> dict:
    """그날(없으면 최근 거래일) 회차 목록 + 선택(없으면 최신) 회차 본문. LLM 0."""
    conn = get_connection()
    try:
        ensure_schema(conn)
        if not day:
            row = conn.execute("SELECT MAX(trade_date) d FROM market_today").fetchone()
            day = row["d"] if row and row["d"] else None
        if not day:
            return {"trade_date": None, "slots": [], "current": None, "next_slot": _next_label()}
        rows = conn.execute("SELECT * FROM market_today WHERE trade_date=? ORDER BY slot", (day,)).fetchall()
        slots = [{"slot": r["slot"], "label": SLOT_LABEL[r["slot"]], "created_at": r["created_at"],
                  "topics": len(json.loads(r["items_json"]))} for r in rows]
        pick = next((r for r in rows if r["slot"] == slot), rows[-1] if rows else None)
        current = None
        if pick:
            sources = json.loads(pick["sources_json"])
            counts = json.loads(pick["counts_json"] or "{}")
            current = {"slot": pick["slot"], "label": SLOT_LABEL[pick["slot"]], "window_start": pick["window_start"],
                       "window_end": pick["window_end"], "created_at": pick["created_at"], "doc_count": pick["doc_count"],
                       "telegram": counts.get("telegram", 0), "news": counts.get("news", 0),
                       "market": json.loads(pick["market_json"]) if pick["market_json"] else None,
                       "topics": [{**t, "sources": [sources[r] | {"ref": r} for r in t["refs"] if r in sources]}
                                  for t in json.loads(pick["items_json"])]}
        return {"trade_date": day, "slots": slots, "current": current, "next_slot": _next_label()}
    finally:
        conn.close()


def _next_label(now: datetime | None = None) -> str | None:
    """오늘 남은 다음 회차 시각(KST) — 화면의 '다음 정리' 표시. 주말이면 None."""
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    if now.weekday() >= 5:
        return None
    return next((SLOT_LABEL[s] for s, t in SLOTS if now.time() < t), None)


def backfill_market(day: str) -> int:
    """이미 만든 회차에 시장 상태가 비어 있으면 채운다(컬럼 추가 전 회차용). 반환 = 채운 회차 수."""
    conn = get_connection()
    try:
        ensure_schema(conn)
        rows = conn.execute("SELECT slot FROM market_today WHERE trade_date=? AND market_json IS NULL", (day,)).fetchall()
        n = 0
        for r in rows:
            m = market_snapshot(date.fromisoformat(day), r["slot"])
            if m:
                conn.execute("UPDATE market_today SET market_json=? WHERE trade_date=? AND slot=?", (json.dumps(m), day, r["slot"]))
                n += 1
        conn.commit()
        return n
    finally:
        conn.close()
