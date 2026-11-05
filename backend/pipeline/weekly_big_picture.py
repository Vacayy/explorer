"""이번 주 큰 그림 — 내러티브를 뼈대로, 장중(Market Today)·미국장(Overnight)을 근거로 줄기 최대 4개 (ia-redesign §4.25, D-313 4, D-315).

흐름: 입력 수집(LLM 0) → 입력 해시 가드(같으면 건너뜀) → sonnet 1콜 → 검증 → `source_digests(kind='big_picture',
key='YYYY-Www')`에 JSON 저장. 같은 주 안에서 다시 만들면 그 주 행을 덮는다(지난 주 행은 남는다).

- 줄기: 합니다체 제목 · 상태(strengthening 강해짐 / mixed 엇갈림 / weakening 약해짐 / new 새로) · 관련 내러티브 id ·
  근거 id 1~3개. 근거는 **원문을 복사하지 않고 id로만** 저장한다 — `mt:<market_today.id>:<화두 순번>`,
  `ov:<us_briefings.trade_date>:<key_points 순번>`. 입력에 없던 id는 버린다(Market Today 인용 검증과 같은 규율).
  화면 문장은 읽을 때 원천에서 꺼낸다(world_reads).
- 줄기 품질(D-315 2): 검증 뒤 서사 2편 이상 또는 근거 id(검증 통과) 1개 이상인 줄기만 남기고, 최대 MAX_STRANDS개.
  빠진 줄기 수는 dropped.thin(근거 부족)·dropped.over(개수 초과)로 job_runs 요약과 저장본에 남는다. 읽을 때도 같은 규칙.
- 전제: 자리 잡은 전제 · 흔들린 전제. 흔들린 전제에 이번 주 서사가 부딪혔으면 `shaken_by`{narrative_id, quote} —
  quote가 그 서사의 제목·3줄 요약에 글자 그대로 없으면 shaken_by만 뺀다. 세계관 브리핑(전제 칸)을 같은 실행에서 대신한다.
- Market Today 연결 수·앞당김은 저장하지 않고 읽을 때 줄기의 서사 주제로 센다(market_today_links.strand_counts).

실행 조건(D-313 4)
- 정기: 매주 월 07:00(launchd `bigpicture`, 놓치면 CATCHUP이 다음 순회에서 보충) — `trigger='weekly'`.
- 이벤트: 16:00 마감 정리 회차 저장 뒤(scripts/market_today.py) 지난 생성 이후 새 내러티브 버전 3편 이상일 때만 —
  `trigger='event'`. 이벤트만의 따로 상한은 없다(D-315 3 — 주간 한도 하나로 센다).
- 수동: '다시 만들기'(POST /api/spine/world/big-picture/rebuild) — 직전 생성 시도 6시간 안이면 거절 — `trigger='manual'`.
- 공통: 이번 주(KST 월요일부터) 생성 시도(정기·조건·다시 만들기 합계) WEEKLY_BUDGET회를 넘으면 거절. 입력 해시가 마지막 생성과 같으면 LLM 없이 건너뜀.
  관리자 플래그 `weekly_big_picture`로 끈다. 모든 실행은 job_runs에 남는다 — 정기는 'weekly_big_picture'(launchd CATCHUP이
  보는 이름), 이벤트·수동은 'weekly_big_picture:event'·':manual'(이벤트의 '건너뜀'이 정기 회차 성공으로 세지지 않게).
  ok(생성)·error(생성 시도 실패) = LLM 시도 1회, skipped = LLM 없음. 쿨다운·한도는 세 이름을 합쳐 센다.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
JOB = "weekly_big_picture"
KIND = "big_picture"
MODEL = "sonnet"
WINDOW_DAYS = 7
MAX_STRANDS = 4             # D-315 2
MIN_STRAND_NARRATIVES = 2   # 줄기를 남기는 근거: 서사 2편 이상 또는
MIN_STRAND_EVIDENCE = 1     # Market Today·Overnight 근거 id 1개 이상(검증 통과)
MAX_EVIDENCE = 3
MAX_PREMISES = 6
EVENT_MIN_VERSIONS = 3      # 이벤트 실행 — 지난 생성 이후 새 내러티브 버전
COOLDOWN_HOURS = 6          # 수동 다시 만들기
WEEKLY_BUDGET = 7           # 주(KST 월~일)당 생성 시도(LLM 호출) 상한 — 정기·이벤트·수동 합계(D-315 3)
MT_ITEM_CHARS = 160         # 프롬프트에 넣는 화두 본문 길이
STATUS = ("strengthening", "mixed", "weakening", "new")
STATUS_KO = {"강해짐": "strengthening", "엇갈림": "mixed", "약해짐": "weakening", "새로": "new"}
_lock = threading.Lock()


# ---------- 시간 ----------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db(dt: datetime) -> str:
    """UTC 'YYYY-MM-DD HH:MM:SS' — DB datetime('now')와 같은 표기."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_db(text: str) -> datetime:
    return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def week_key(now: datetime | None = None) -> str:
    d = (now or _now()).astimezone(KST).date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _week_start_utc(now: datetime) -> str:
    d = now.astimezone(KST).date()
    monday = datetime.combine(d - timedelta(days=d.weekday()), datetime.min.time(), KST)
    return _db(monday)


# ---------- 입력 수집 (LLM 0) ----------

def _summary(body: str | None) -> str:
    from pipeline.narrative import _summary as s
    return s(body) or ""


def gather(conn, now: datetime | None = None) -> dict:
    """최근 7일 근거. narratives = 새 버전 + 이번 주 Market Today에 걸린 살아 있는 서사(최신 버전)."""
    now = now or _now()
    since = _db(now - timedelta(days=WINDOW_DAYS))
    rows = conn.execute("""
        SELECT n.id, n.topic, n.version, n.title, n.body, n.created_at,
               (SELECT MIN(created_at) FROM narratives f WHERE f.topic=n.topic AND COALESCE(f.kind,'topic')='topic') first_at
        FROM narratives n
        WHERE COALESCE(n.kind,'topic')='topic' AND n.title IS NOT NULL AND n.created_at >= ? AND n.created_at <= ?
        ORDER BY n.created_at DESC""", (since, _db(now))).fetchall()
    # 같은 주제가 창 안에 여러 버전이면 최신 버전만 줄기 후보로(옛 버전 수는 versions로)
    narratives: dict[str, dict] = {}
    for r in rows:
        n = narratives.get(r["topic"])
        if n:
            n["versions"] += 1
            continue
        narratives[r["topic"]] = {"id": r["id"], "topic": r["topic"], "version": r["version"], "title": r["title"],
                                  "summary": _summary(r["body"]), "created_at": r["created_at"],
                                  "is_new": bool(r["first_at"] and r["first_at"] >= since), "versions": 1, "in_window": True}
    mt_sessions, mt_items, freq = [], {}, {}
    try:
        from pipeline.market_today_links import ensure_schema, frequency
        ensure_schema(conn)
        sess = conn.execute("SELECT id, trade_date, slot, items_json, created_at FROM market_today "
                            "WHERE created_at >= ? AND created_at <= ? ORDER BY trade_date, slot", (since, _db(now))).fetchall()
        freq = frequency(conn, (now.astimezone(KST).date() - timedelta(days=now.astimezone(KST).weekday())).isoformat())
        links: dict[tuple[int, int], list[str]] = {}
        for r in conn.execute("SELECT mt_id, item_idx, narrative_topic FROM market_today_links"):
            links.setdefault((r[0], r[1]), []).append(r[2])
        for s in sess:
            mt_sessions.append({"id": s["id"], "trade_date": s["trade_date"], "slot": s["slot"], "created_at": s["created_at"]})
            for i, it in enumerate(json.loads(s["items_json"] or "[]")):
                mt_items[f"mt:{s['id']}:{i}"] = {"session": s["id"], "trade_date": s["trade_date"], "slot": s["slot"],
                                                 "title": it.get("title") or "", "body": it.get("body") or "",
                                                 "topics": links.get((s["id"], i), [])}
    except Exception:  # noqa: BLE001 — Market Today 표가 없는 DB: 근거 범위 0회차(Partial)
        mt_sessions, mt_items, freq = [], {}, {}
    # 이번 주 Market Today에 걸린 살아 있는 서사도 줄기 후보로(창 밖 버전이라도 — AI·반도체처럼 화두에 자주 오르는 서사)
    hot = [t for t in freq if t not in narratives]
    if hot:
        q = ",".join("?" * len(hot))
        for r in conn.execute(f"""SELECT id, topic, version, title, body, created_at FROM narratives
                WHERE topic IN ({q}) AND superseded_at IS NULL AND COALESCE(kind,'topic')='topic' AND title IS NOT NULL""", hot):
            narratives[r["topic"]] = {"id": r["id"], "topic": r["topic"], "version": r["version"], "title": r["title"],
                                      "summary": _summary(r["body"]), "created_at": r["created_at"], "is_new": False,
                                      "versions": 0, "in_window": False}
    for t, n in narratives.items():
        f = freq.get(t)
        n["mt_topics"], n["mt_sessions"] = (f["topics"], f["sessions"]) if f else (0, 0)
    overnight = {}
    ov_rows = conn.execute("SELECT trade_date, synthesis_json, created_at FROM us_briefings WHERE trade_date >= ? "
                           "ORDER BY trade_date", ((now.astimezone(KST).date() - timedelta(days=WINDOW_DAYS)).isoformat(),)).fetchall()
    ov_days = []
    for r in ov_rows:
        kp = (json.loads(r["synthesis_json"] or "{}") or {}).get("key_points") or []
        if not kp:
            continue
        ov_days.append({"trade_date": r["trade_date"], "created_at": r["created_at"]})
        for i, text in enumerate(kp):
            if isinstance(text, str) and text.strip():
                overnight[f"ov:{r['trade_date']}:{i}"] = {"trade_date": r["trade_date"], "text": text.strip()}
    stamps = [n["created_at"] for n in narratives.values() if n["in_window"]] + [s["created_at"] for s in mt_sessions] + \
             [d["created_at"] for d in ov_days]
    return {
        "narratives": sorted(narratives.values(), key=lambda n: n["created_at"] or "", reverse=True),
        "mt_sessions": mt_sessions, "mt_items": mt_items, "overnight_days": ov_days, "overnight": overnight,
        "prev": _previous(conn),
        "inputs": {"narratives": sum(1 for n in narratives.values() if n["in_window"]),
                   "mt_sessions": len(mt_sessions), "overnight_days": len(ov_days)},
        "inputs_as_of": max(stamps) if stamps else None,
    }


def _previous(conn) -> dict:
    """직전 큰 그림의 줄기·전제(있으면), 없으면 세계관 브리핑의 전제 — 상태(강해짐·약해짐)와 '흔들림' 판단의 기준."""
    last = latest(conn)
    if last:
        d = last["data"]
        return {"strands": [{"title": s["title"], "status": s["status"]} for s in d.get("strands", [])],
                "settled": [p["text"] for p in d.get("premises", {}).get("settled", [])],
                "contested": [p["text"] for p in d.get("premises", {}).get("contested", [])]}
    from pipeline.world_reads import premises_from_briefing
    from pipeline.worldview import get_cached
    wv = get_cached(conn)
    p = premises_from_briefing(wv["digest"] if wv else None)
    return {"strands": [], "settled": p["settled"], "contested": p["contested"]}


def inputs_hash(m: dict) -> str:
    """바깥 입력(서사 버전·Market Today 회차·Overnight)만. 직전 큰 그림(prev)은 넣지 않는다 — 넣으면 생성할 때마다 해시가 바뀐다."""
    parts = [f"n:{n['id']}" for n in m["narratives"]]
    parts += [f"m:{s['id']}:{s['created_at']}" for s in m["mt_sessions"]]
    parts += [f"o:{d['trade_date']}:{d['created_at']}" for d in m["overnight_days"]]
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()


# ---------- 저장분 ----------

def latest(conn) -> dict | None:
    """가장 최근 생성 → {key, created_at, inputs_hash, data}."""
    r = conn.execute("SELECT key, digest, doc_ids_hash, created_at FROM source_digests WHERE kind=? "
                     "ORDER BY created_at DESC, id DESC LIMIT 1", (KIND,)).fetchone()
    if not r:
        return None
    try:
        data = json.loads(r["digest"] or "{}")
    except ValueError:
        return None
    return {"key": r["key"], "created_at": r["created_at"], "inputs_hash": r["doc_ids_hash"], "data": data}


def _attempts(conn, since: str) -> list[str]:
    """생성 시도(LLM 호출) 시각 — job_runs ok·error."""
    return [r[0] for r in conn.execute("SELECT ran_at FROM job_runs WHERE (job=? OR job LIKE ?) AND status IN ('ok','error') "
                                       "AND ran_at >= ? ORDER BY ran_at", (JOB, JOB + ":%", since))]


def rebuild_state(conn, now: datetime | None = None) -> dict:
    """'다시 만들기' 가능 여부 — {available, reason: cooldown|budget|unavailable|None, retry_at(UTC DB 표기), budget_left}."""
    from pipeline.enrich import llm_engine
    now = now or _now()
    week = _attempts(conn, _week_start_utc(now))
    left = max(0, WEEKLY_BUDGET - len(week))
    recent = _attempts(conn, _db(now - timedelta(hours=COOLDOWN_HOURS)))
    if recent:
        return {"available": False, "reason": "cooldown", "budget_left": left,
                "retry_at": _db(_parse_db(recent[-1]) + timedelta(hours=COOLDOWN_HOURS))}
    if left == 0:
        nxt = datetime.combine(now.astimezone(KST).date() - timedelta(days=now.astimezone(KST).weekday()) + timedelta(days=7),
                               datetime.min.time(), KST)
        return {"available": False, "reason": "budget", "budget_left": 0, "retry_at": _db(nxt)}
    if llm_engine() != "claude-code":
        return {"available": False, "reason": "unavailable", "budget_left": left, "retry_at": None}
    return {"available": True, "reason": None, "budget_left": left, "retry_at": None}


def versions_since(conn, stamp: str | None) -> int:
    if not stamp:
        return conn.execute("SELECT COUNT(*) FROM narratives WHERE COALESCE(kind,'topic')='topic' "
                            "AND created_at >= datetime('now', ?)", (f"-{WINDOW_DAYS} days",)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM narratives WHERE COALESCE(kind,'topic')='topic' AND created_at > ?",
                        (stamp,)).fetchone()[0]


def event_due(conn, now: datetime | None = None) -> tuple[bool, str]:
    """16:00 마감 정리 뒤 추가 실행 조건 — 지난 생성 이후 새 버전 3편 이상. 따로 상한 없이 주간 한도로만 센다(D-315 3)."""
    last = latest(conn)
    n = versions_since(conn, last["created_at"] if last else None)
    if n < EVENT_MIN_VERSIONS:
        return False, f"지난 생성 뒤 새 버전 {n}편(<{EVENT_MIN_VERSIONS})"
    return True, f"지난 생성 뒤 새 버전 {n}편"


# ---------- 프롬프트 · 검증 ----------

def build_prompt(m: dict) -> str:
    def nline(n):
        tag = " [이번 주 새 서사]" if n["is_new"] else ("" if n["in_window"] else " [이번 주 새 버전 없음 · Market Today에 자주 나옴]")
        mt = f" · Market Today 화두 {n['mt_topics']}·{n['mt_sessions']}회차" if n["mt_topics"] else ""
        return f"- id={n['id']} | {n['topic']} v{n['version']} ({(n['created_at'] or '')[:10]}){tag}{mt}\n  제목: {n['title']}\n  요약: {n['summary'][:260]}"
    mt_lines = [f"- {k} | {v['trade_date']} {v['slot']} | {v['title']} — {v['body'][:MT_ITEM_CHARS]}"
                + (f" (연결 서사: {', '.join(v['topics'])})" if v["topics"] else "") for k, v in m["mt_items"].items()]
    ov_lines = [f"- {k} | {v['text']}" for k, v in m["overnight"].items()]
    prev = m["prev"]
    prev_lines = [f"- [{s['status']}] {s['title']}" for s in prev["strands"]]
    return (
        "당신은 1인 리서치센터의 센터장입니다. 아래 재료로 '이번 주 큰 그림'을 정리합니다. 재료는 최근 7일 새로 쓰인 내러티브(뼈대), "
        "장중 Market Today 화두와 미국장 Overnight 핵심 요약(근거)입니다.\n"
        "할 일\n"
        "1. 여러 서사를 관통하는 '줄기'를 최대 4개 묶습니다. 줄기마다 서사 2편 이상 또는 아래 근거 id 1개 이상이 받쳐야 합니다 — "
        "서사 한 편뿐이고 근거도 없는 묶음은 만들지 않습니다. 줄기마다:\n"
        "   - title: 합니다체 한 줄(60자 안). 판단·매매 권유 금지, 무엇이 어디로 옮겨 가는지를 씁니다.\n"
        "   - status: strengthening(강해짐) | mixed(엇갈림) | weakening(약해짐) | new(새로) 중 하나. 직전 큰 그림 줄기와 비교해 정합니다. "
        "직전 줄기에 없던 흐름이면 new.\n"
        "   - narratives: 이 줄기를 이루는 내러티브 id 목록(아래 재료의 id=… 숫자만, 1~4개).\n"
        "   - evidence: 줄기를 뒷받침하는 근거 id 1~3개(아래 Market Today의 mt:… 또는 Overnight의 ov:… 를 글자 그대로). "
        "근거 문장을 새로 쓰지 말고 id만 적습니다. 맞는 근거가 없으면 빈 목록.\n"
        "2. 전제 칸: settled(자리 잡은 전제)와 contested(흔들린 전제)를 각각 2~5개, 합니다체 한 문장씩. 직전 전제 목록을 이어받되 "
        "이번 주 서사로 바뀐 것은 고칩니다. 이번 주 내러티브가 기존 전제와 부딪혔으면 그 전제를 contested에 두고 "
        "shaken_by에 부딪힌 내러티브 id와 그 내러티브 제목 또는 요약에서 글자 그대로 복사한 인용(20~80자)을 붙입니다. 없으면 shaken_by는 null.\n"
        "규율: 재료에 없는 사실 금지. 내부 라벨(id 숫자, mt:, ov:)을 title·전제 문장에 쓰지 않습니다. 존댓말 합니다체.\n"
        'JSON만 출력: {"strands": [{"title": "…", "status": "strengthening", "narratives": [123], "evidence": ["mt:5:0", "ov:2026-11-03:1"]}], '
        '"premises": {"settled": [{"text": "…"}], "contested": [{"text": "…", "shaken_by": {"narrative_id": 123, "quote": "…"}}]}}\n\n'
        "[직전 큰 그림 줄기]\n" + ("\n".join(prev_lines) or "- 없음(첫 생성)") +
        "\n\n[직전 전제 — 자리 잡은 것]\n" + ("\n".join(f"- {t}" for t in prev["settled"]) or "- 없음") +
        "\n\n[직전 전제 — 흔들린 것]\n" + ("\n".join(f"- {t}" for t in prev["contested"]) or "- 없음") +
        "\n\n[내러티브]\n" + ("\n".join(nline(n) for n in m["narratives"]) or "- 없음") +
        "\n\n[Market Today 화두]\n" + ("\n".join(mt_lines) or "- 없음") +
        "\n\n[Overnight 핵심 요약]\n" + ("\n".join(ov_lines) or "- 없음")
    )


def _norm(text) -> str:
    from pipeline.us_briefing import _norm_quote
    return _norm_quote(str(text or "")).strip("\"'“”‘’ ")


def validate(raw, m: dict) -> dict:
    """LLM 출력 → 저장할 JSON. 입력에 없던 서사·근거 id, 허용 밖 상태, 원문에 없는 인용은 버린다."""
    raw = raw if isinstance(raw, dict) else {}
    by_id = {n["id"]: n for n in m["narratives"]}
    evid = set(m["mt_items"]) | set(m["overnight"])
    dropped = {"strands": 0, "narratives": 0, "evidence": 0, "quotes": 0, "thin": 0, "over": 0}
    strands = []
    for s in raw.get("strands") or []:
        if not isinstance(s, dict) or not str(s.get("title") or "").strip():
            dropped["strands"] += 1
            continue
        status = str(s.get("status") or "").strip()
        status = STATUS_KO.get(status, status)
        ids = []
        for x in s.get("narratives") or []:
            try:
                i = int(x)
            except (TypeError, ValueError):
                i = None
            if i in by_id and i not in ids:
                ids.append(i)
            else:
                dropped["narratives"] += 1
        if status not in STATUS or not ids:
            dropped["strands"] += 1
            continue
        ev = []
        for e in s.get("evidence") or []:
            e = str(e).strip()
            if e in evid and e not in ev:
                ev.append(e)
            else:
                dropped["evidence"] += 1
        strands.append({"title": str(s["title"]).strip()[:120], "status": status, "narratives": ids[:4], "evidence": ev[:MAX_EVIDENCE]})
    premises: dict[str, list] = {"settled": [], "contested": []}
    p = raw.get("premises") if isinstance(raw.get("premises"), dict) else {}
    for side in ("settled", "contested"):
        for it in p.get(side) or []:
            text = it.get("text") if isinstance(it, dict) else it
            if not isinstance(text, str) or not text.strip() or len(premises[side]) >= MAX_PREMISES:
                continue
            item = {"text": text.strip()[:200], "shaken_by": None}
            sb = it.get("shaken_by") if isinstance(it, dict) else None
            if side == "contested" and isinstance(sb, dict):
                try:
                    nid = int(sb.get("narrative_id"))
                except (TypeError, ValueError):
                    nid = None
                q = _norm(sb.get("quote"))
                n = by_id.get(nid)
                if n and len(q) >= 8 and (q in _norm(n["title"]) or q in _norm(n["summary"])):
                    item["shaken_by"] = {"narrative_id": nid, "quote": q}
                else:
                    dropped["quotes"] += 1
            premises[side].append(item)
    kept, dropped["thin"], dropped["over"] = keep_strands(strands)
    return {"strands": kept, "premises": premises, "dropped": dropped}


def strand_backed(s: dict) -> bool:
    """줄기를 남길 근거가 있나 — 서사 2편 이상 또는 근거 id 1개 이상(D-315 2)."""
    return len(s.get("narratives") or []) >= MIN_STRAND_NARRATIVES or len(s.get("evidence") or []) >= MIN_STRAND_EVIDENCE


def keep_strands(strands: list[dict]) -> tuple[list[dict], int, int]:
    """근거가 받치는 줄기만 앞에서부터 MAX_STRANDS개 → (남긴 줄기, 근거 부족으로 뺀 수, 개수 초과로 뺀 수)."""
    backed = [s for s in strands if strand_backed(s)]
    return backed[:MAX_STRANDS], len(strands) - len(backed), max(0, len(backed) - MAX_STRANDS)


# ---------- 실행 ----------

def job_name(trigger: str) -> str:
    return JOB if trigger == "weekly" else f"{JOB}:{trigger}"


def _record(trigger: str, status: str, summary: str, t0: float) -> None:
    from pipeline.ops import record_run
    record_run(job_name(trigger), status, summary, int((time.time() - t0) * 1000))


def run(trigger: str = "weekly", call=None, now: datetime | None = None) -> dict:
    """한 번 실행 → {status: ok|skipped|cooldown|budget|unavailable|failed|empty|off, ...}. call = 테스트용 LLM 대역(prompt → dict|str)."""
    from database import get_connection
    from pipeline.enrich import _call_claude_code, _parse_json, llm_engine
    from pipeline.ops import flag_enabled
    t0, now = time.time(), now or _now()
    if not flag_enabled(JOB):
        _record(trigger, "skipped", f"{trigger} · 관리자 off", t0)
        return {"status": "off"}
    if not _lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "이미 만드는 중"}
    conn = get_connection()
    try:
        if trigger == "event":
            due, why = event_due(conn, now)
            if not due:
                _record("event", "skipped", f"event · {why}", t0)
                return {"status": "skipped", "reason": why}
        state = rebuild_state(conn, now)
        if trigger == "manual" and state["reason"] == "cooldown":
            return {"status": "cooldown", "retry_at": state["retry_at"]}
        if state["reason"] == "budget":
            _record(trigger, "skipped", f"{trigger} · 이번 주 생성 {WEEKLY_BUDGET}회 다 씀", t0)
            return {"status": "budget", "retry_at": state["retry_at"]}
        m = gather(conn, now)
        if not m["narratives"]:
            _record(trigger, "skipped", f"{trigger} · 최근 7일 새 내러티브 없음", t0)
            return {"status": "empty"}
        h = inputs_hash(m)
        last = latest(conn)
        if last and last["inputs_hash"] == h:
            _record(trigger, "skipped", f"{trigger} · 입력 그대로({last['key']})", t0)
            return {"status": "skipped", "reason": "입력 그대로", "key": last["key"]}
        if call is None and llm_engine() != "claude-code":
            _record(trigger, "skipped", f"{trigger} · LLM 미가용", t0)
            return {"status": "unavailable"}
        try:
            out = (call or (lambda p: _call_claude_code(p, model=MODEL, timeout=300)))(build_prompt(m))
            data = _parse_json(out) if isinstance(out, str) else out
        except Exception as e:  # noqa: BLE001 — 이전 저장분은 그대로 둔다
            _record(trigger, "error", f"{trigger} · 생성 실패 {type(e).__name__}: {str(e)[:150]}", t0)
            return {"status": "failed", "reason": f"{type(e).__name__}"}
        v = validate(data, m)
        if not v["strands"]:
            _record(trigger, "error", f"{trigger} · 검증 뒤 줄기 0 · 버림 {v['dropped']}", t0)
            return {"status": "failed", "reason": "검증을 통과한 줄기 없음", "dropped": v["dropped"]}
        key = week_key(now)
        digest = {"version": 1, "trigger": trigger, "generated_at": _db(now), "inputs": m["inputs"],
                  "inputs_as_of": m["inputs_as_of"], "strands": v["strands"], "premises": v["premises"],
                  "dropped": v["dropped"]}
        conn.execute("""INSERT INTO source_digests (kind, key, digest, doc_count, doc_ids_hash, model, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(kind, key) DO UPDATE SET digest=excluded.digest, doc_count=excluded.doc_count,
                          doc_ids_hash=excluded.doc_ids_hash, model=excluded.model, created_at=excluded.created_at""",
                     (KIND, key, json.dumps(digest, ensure_ascii=False), len(m["narratives"]), h, MODEL, _db(now)))
        conn.commit()
        _record(trigger, "ok", f"{trigger} · {key} · 줄기 {len(v['strands'])} · 전제 {len(v['premises']['settled'])}/"
                      f"{len(v['premises']['contested'])} · 버림 {v['dropped']}", t0)
        return {"status": "ok", "key": key, "strands": len(v["strands"]), "dropped": v["dropped"]}
    finally:
        conn.close()
        _lock.release()


# ---------- 읽기 (GET /api/spine/world/big-picture) — 저장분만, LLM 0 ----------

def _slot_label(slot: str) -> str:
    from pipeline.market_today import SLOT_LABEL
    return SLOT_LABEL.get(slot, slot)


def resolve_evidence(conn, ids: list[str]) -> list[dict]:
    """근거 id → 화면 줄 {kind, ref, label, text}. 원천에서 사라진 id는 뺀다."""
    out = []
    for ref in ids:
        mt = re.fullmatch(r"mt:(\d+):(\d+)", ref)
        ov = re.fullmatch(r"ov:(\d{4}-\d{2}-\d{2}):(\d+)", ref)
        if mt:
            try:
                r = conn.execute("SELECT trade_date, slot, items_json FROM market_today WHERE id=?", (int(mt[1]),)).fetchone()
            except Exception:  # noqa: BLE001 — 표 없음
                r = None
            items = json.loads(r["items_json"] or "[]") if r else []
            i = int(mt[2])
            if r and i < len(items) and items[i].get("title"):
                d = date.fromisoformat(r["trade_date"])
                out.append({"kind": "market_today", "ref": ref, "label": f"Market Today {d.month}/{d.day} {_slot_label(r['slot'])}",
                            "text": items[i]["title"], "date": r["trade_date"]})
        elif ov:
            r = conn.execute("SELECT synthesis_json FROM us_briefings WHERE trade_date=?", (ov[1],)).fetchone()
            kp = ((json.loads(r["synthesis_json"] or "{}") or {}).get("key_points") or []) if r else []
            i = int(ov[2])
            if i < len(kp) and isinstance(kp[i], str) and kp[i].strip():
                d = date.fromisoformat(ov[1])
                out.append({"kind": "overnight", "ref": ref, "label": f"Overnight {d.month}/{d.day}", "text": kp[i].strip(),
                            "date": ov[1]})
    return out


def read_generated(conn) -> dict | None:
    """가장 최근 생성 → 화면용 줄기·전제(서사 칩·근거 줄·이번 주 Market Today 연결 수를 원천에서 붙임). 없으면 None."""
    last = latest(conn)
    if not last:
        return None
    d = last["data"]
    ids = sorted({i for s in d.get("strands", []) for i in s.get("narratives", [])} |
                 {p["shaken_by"]["narrative_id"] for p in d.get("premises", {}).get("contested", []) if p.get("shaken_by")})
    meta = {}
    if ids:
        q = ",".join("?" * len(ids))
        for r in conn.execute(f"""SELECT n.id, n.topic, n.version, n.created_at,
                (SELECT MIN(created_at) FROM narratives f WHERE f.topic=n.topic AND COALESCE(f.kind,'topic')='topic') first_at
                FROM narratives n WHERE n.id IN ({q})""", ids):
            meta[r["id"]] = {"narrative_id": r["id"], "topic": r["topic"], "version": r["version"], "created_at": r["created_at"],
                             "is_new": bool(r["first_at"] and r["first_at"] >= _db(_parse_db(d["generated_at"]) - timedelta(days=WINDOW_DAYS)))}
    try:
        from pipeline.market_today_links import boosted_topics, ensure_schema, frequency, strand_counts
        ensure_schema(conn)
        freq, boosted = frequency(conn), boosted_topics(conn)
    except Exception:  # noqa: BLE001 — Market Today 표 없음
        freq, boosted, strand_counts = {}, set(), None
    strands = []
    for s in keep_strands(d.get("strands", []))[0]:   # D-315 이전 저장분(줄기 5개·약한 묶음)도 같은 규칙으로
        chips = [meta[i] for i in s.get("narratives", []) if i in meta]
        topics = [c["topic"] for c in chips]
        counts = strand_counts(conn, topics, freq, boosted) if strand_counts else {"mt_topics": 0, "mt_sessions": 0, "boost": False}
        strands.append({"title": s["title"], "status": s["status"], "narratives": chips, **counts,
                        "evidence": resolve_evidence(conn, s.get("evidence", []))})
    prem = {}
    for side in ("settled", "contested"):
        prem[side] = []
        for p in d.get("premises", {}).get(side, []):
            sb = p.get("shaken_by")
            m = meta.get(sb["narrative_id"]) if sb else None
            prem[side].append({"text": p["text"], "shaken_by": {**m, "quote": sb["quote"]} if m else None})
    return {"key": last["key"], "generated_at": d.get("generated_at") or last["created_at"], "trigger": d.get("trigger"),
            "inputs": d.get("inputs") or {"narratives": 0, "mt_sessions": 0, "overnight_days": 0},
            "inputs_as_of": d.get("inputs_as_of"), "strands": strands, "premises": prem}
