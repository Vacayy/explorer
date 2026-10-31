"""관측 — 잘 도는가 · 얼마나 드는가 · 무엇을 쓰는가 · 도움이 되는가 (docs/specs/observability.md, D-283).

외부 관측 도구 없이 SQLite에 쌓고, 관리자 '관측' 탭(`summary`)·주간 텔레그램(`weekly_message`)·
상태가 바뀔 때만 보내는 즉시 경고(`check_alerts`)로 본다. 지표는 그것으로 내릴 결정에 묶는다.
"""
import json
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone

from database import get_connection

# ---------- API 요청 집계 (미들웨어) ----------

BUCKETS = ((100, "b100"), (300, "b300"), (1000, "b1000"), (3000, "b3000"))
SKIP_PREFIXES = ("/api/spine/client-errors", "/api/spine/usage", "/docs", "/openapi.json", "/redoc")
FLUSH_SECONDS = 60

_lock = threading.Lock()
_buf: dict[tuple, dict] = {}
_last_flush = time.monotonic()


def record_request(method: str, route: str, status: int, ms: float) -> None:
    """요청 하나를 메모리에 더한다. 행은 (시각 단위, 메서드, 경로 패턴, 상태 계층)마다 하나 — 요청마다 쌓지 않는다."""
    if not route.startswith("/api") or route.startswith(SKIP_PREFIXES):
        return
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00")
    key = (hour, method, route, f"{status // 100}xx")
    with _lock:
        b = _buf.setdefault(key, {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "b100": 0, "b300": 0, "b1000": 0, "b3000": 0, "bslow": 0})
        b["count"] += 1
        b["total_ms"] += ms
        b["max_ms"] = max(b["max_ms"], ms)
        b[next((col for lim, col in BUCKETS if ms <= lim), "bslow")] += 1
    if time.monotonic() - _last_flush > FLUSH_SECONDS:
        flush()


def flush() -> int:
    """메모리 집계를 DB에 더한다. DB가 잠겨 있으면 다음 번에 다시(버퍼를 되돌린다)."""
    global _buf, _last_flush
    with _lock:
        buf, _buf = _buf, {}
        _last_flush = time.monotonic()
    if not buf:
        return 0
    try:
        conn = get_connection()
        try:
            for (hour, method, route, sc), b in buf.items():
                conn.execute(
                    "INSERT INTO api_requests_hourly (hour, method, route, status_class, count, total_ms, max_ms, b100, b300, b1000, b3000, bslow) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(hour, method, route, status_class) DO UPDATE SET "
                    "count=count+excluded.count, total_ms=total_ms+excluded.total_ms, max_ms=max(max_ms, excluded.max_ms), "
                    "b100=b100+excluded.b100, b300=b300+excluded.b300, b1000=b1000+excluded.b1000, b3000=b3000+excluded.b3000, bslow=bslow+excluded.bslow",
                    (hour, method, route, sc, b["count"], b["total_ms"], b["max_ms"], b["b100"], b["b300"], b["b1000"], b["b3000"], b["bslow"]))
            conn.commit()
        finally:
            conn.close()
        return len(buf)
    except Exception as e:  # noqa: BLE001 — 관측이 요청을 막으면 안 된다. 다음 번에 다시 더한다
        with _lock:
            for k, b in buf.items():
                cur = _buf.setdefault(k, {kk: 0 for kk in b})
                for kk, v in b.items():
                    cur[kk] = max(cur[kk], v) if kk == "max_ms" else cur[kk] + v
        print(f"[observe] 요청 집계 저장 실패(다음에 재시도): {e}")
        return 0


def p95_ms(row) -> int | None:
    """응답시간 구간으로 p95 근사 — 구간 상한을 돌려준다(>3000ms는 max_ms)."""
    n = row["count"]
    if not n:
        return None
    need, acc = 0.95 * n, 0
    for lim, col in BUCKETS:
        acc += row[col]
        if acc >= need:
            return lim
    return int(row["max_ms"])


# ---------- 사용 이벤트 ----------

EVENT_TYPES = {"view", "leave", "action", "open"}


def save_events(events: list[dict]) -> int:
    rows = [(e["ts"], e.get("session"), e["type"], e["name"][:200], (e.get("ref") or None) and e["ref"][:200],
             (e.get("entity") or None) and str(e["entity"])[:100], e.get("dwell_ms"))
            for e in events if e.get("type") in EVENT_TYPES and e.get("name")]
    if not rows:
        return 0
    conn = get_connection()
    try:
        conn.executemany("INSERT INTO usage_events (ts, session, type, name, ref, entity, dwell_ms) VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


# ---------- 요약 (관리자 '관측' 탭) ----------

JOB_NAMES = {"pf_intraday": "장중 포트폴리오 알림", "ext_series": "외부 시계열 수집", "image_backfill": "이미지 백필",
             "scan_actions": "액션 스캔", "chain": "30분 체인", "cm_extract": "실적 발언 추출", "send_briefing": "아침 브리핑",
             "transcript": "컨콜(정리·추출)", "narrative": "내러티브", "enrich": "문서 태깅", "call_reaction": "시장 반응",
             "us_briefing": "미국장 브리핑", "image_reading": "이미지 읽기", "digests": "다이제스트", "live_contracts": "실제 응답 계약 검사",
             "earnings_chain": "실적 시즌 체인", "call_momentum": "실적 발언 모멘텀", "llm_probe": "LLM 연결 점검"}


def _name(job: str) -> str:
    return JOB_NAMES.get(job.removeprefix("sched:"), job.removeprefix("sched:"))


_SCHED: dict | None = None


def _sched_records() -> dict:
    """정기 실행기 래퍼 기록(sched:<label>) → 그 작업이 스스로 남기는 기록 이름(install_launchd.CATCHUP['record']).
    스스로 남기는 작업은 래퍼 기록을 문제 목록에서 뺀다(같은 실패가 두 번 잡힌다)."""
    global _SCHED
    if _SCHED is None:
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
            from install_launchd import CATCHUP
            _SCHED = {k: v.get("record") for k, v in CATCHUP.items()}
        except Exception:  # noqa: BLE001 — 설정을 못 읽으면 래퍼 기록도 그대로 보인다
            _SCHED = {}
    return _SCHED


def _duplicate(job: str) -> bool:
    return job.startswith("sched:") and bool(_sched_records().get(job.removeprefix("sched:")))


def job_problems(conn, days: int = 7) -> dict:
    """작업별 성공률 + 연속 실패(최근 연속 error) + 만성 부분 성공(최근 5회 모두 partial)."""
    rows = [dict(r) for r in conn.execute(
        "SELECT job, count(*) n, sum(status='ok') ok, sum(status='error') err, sum(status='partial') part, avg(duration_ms) avg_ms "
        "FROM job_runs WHERE ran_at >= datetime('now', ?) AND status != 'skipped' GROUP BY job", (f"-{days} days",))]
    streaks, chronic = [], []
    for r in rows:
        if _duplicate(r["job"]):
            continue
        recent = [x[0] for x in conn.execute("SELECT status FROM job_runs WHERE job=? AND status != 'skipped' ORDER BY id DESC LIMIT 5", (r["job"],))]
        k = 0
        for s in recent:
            if s != "error":
                break
            k += 1
        if k >= 2:
            last = conn.execute("SELECT summary FROM job_runs WHERE job=? AND status='error' ORDER BY id DESC LIMIT 1", (r["job"],)).fetchone()
            streaks.append({"job": r["job"], "name": _name(r["job"]), "streak": k, "last": (last[0] or "")[:160] if last else ""})
        if len(recent) >= 5 and all(s == "partial" for s in recent):
            chronic.append({"job": r["job"], "name": _name(r["job"]), "runs": r["n"]})
    failing = sorted([r for r in rows if r["err"] and not _duplicate(r["job"])], key=lambda r: -r["err"])
    for r in failing:
        last = conn.execute("SELECT summary FROM job_runs WHERE job=? AND status='error' ORDER BY id DESC LIMIT 1", (r["job"],)).fetchone()
        r["name"] = _name(r["job"])
        r["last"] = (last[0] or "")[:160] if last else ""
    total = {"runs": sum(r["n"] for r in rows), "ok": sum(r["ok"] for r in rows), "err": sum(r["err"] for r in rows),
             "partial": sum(r["part"] for r in rows)}
    return {"total": total, "failing": failing[:8], "streaks": streaks, "chronic": chronic,
            "table": sorted(({**r, "name": _name(r["job"])} for r in rows), key=lambda r: (-(r["err"] or 0), -(r["part"] or 0), r["job"]))}


def api_health(conn, days: int = 7) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:00")
    rows = [dict(r) for r in conn.execute(
        "SELECT method, route, sum(count) n, sum(CASE WHEN status_class='5xx' THEN count ELSE 0 END) e5, sum(total_ms) tms, max(max_ms) mx, "
        "sum(b100) b100, sum(b300) b300, sum(b1000) b1000, sum(b3000) b3000, sum(bslow) bslow FROM api_requests_hourly "
        "WHERE hour >= ? GROUP BY method, route", (since,))]
    for r in rows:
        r["count"], r["max_ms"] = r["n"], r["mx"]
        r["p95_ms"] = p95_ms(r)
        r["avg_ms"] = round(r["tms"] / r["n"]) if r["n"] else None
        r["err_rate"] = round(r["e5"] / r["n"] * 100, 1) if r["n"] else 0
    total = sum(r["n"] for r in rows)
    first = conn.execute("SELECT min(hour) FROM api_requests_hourly").fetchone()[0]
    return {"since": first, "requests": total, "errors_5xx": sum(r["e5"] for r in rows),
            "worst_errors": [_api(r) for r in sorted([r for r in rows if r["e5"]], key=lambda r: -r["e5"])[:5]],
            "slowest": [_api(r) for r in sorted([r for r in rows if r["n"] >= 5], key=lambda r: -(r["p95_ms"] or 0))[:5]],
            "busiest": [_api(r) for r in sorted(rows, key=lambda r: -r["n"])[:5]]}


def _api(r: dict) -> dict:
    return {"endpoint": f"{r['method']} {r['route']}", "count": r["n"], "errors_5xx": r["e5"], "err_rate": r["err_rate"],
            "avg_ms": r["avg_ms"], "p95_ms": r["p95_ms"], "max_ms": round(r["mx"] or 0)}


def costs(conn, days: int = 7) -> dict:
    cur = conn.execute("SELECT round(sum(cost_usd),2), count(*) FROM llm_calls WHERE created_at >= datetime('now', ?)", (f"-{days} days",)).fetchone()
    prev = conn.execute("SELECT round(sum(cost_usd),2) FROM llm_calls WHERE created_at >= datetime('now', ?) AND created_at < datetime('now', ?)",
                        (f"-{days * 2} days", f"-{days} days")).fetchone()[0]
    by_job = [dict(r) for r in conn.execute(
        "SELECT job, round(sum(cost_usd),2) usd, count(*) calls, sum(ok=0) failed, "
        "round(100.0*sum(coalesce(cache_read_tokens,0))/max(1, sum(input_tokens+coalesce(cache_create_tokens,0)+coalesce(cache_read_tokens,0)))) cache_pct "
        "FROM llm_calls WHERE created_at >= datetime('now', ?) GROUP BY job ORDER BY usd DESC LIMIT 10", (f"-{days} days",))]
    for r in by_job:
        r["name"] = _name(r["job"])
        r["share"] = round(r["usd"] / cur[0] * 100) if cur[0] else 0
    daily = [{"day": d, "usd": u} for d, u in conn.execute(
        "SELECT date(created_at, '+9 hours') d, round(sum(cost_usd),2) FROM llm_calls WHERE created_at >= datetime('now', '-14 days') GROUP BY d ORDER BY d")]
    return {"usd": cur[0] or 0, "calls": cur[1], "prev_usd": prev or 0,
            "change_pct": round(((cur[0] or 0) / prev - 1) * 100) if prev else None, "by_job": by_job, "daily": daily}


def usage(conn, days: int = 7) -> dict:
    first = conn.execute("SELECT min(ts) FROM usage_events").fetchone()[0]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    screens = [dict(r) for r in conn.execute(
        # 머문 시간 = 그 화면 leave의 합 ÷ 방문 수(탭을 숨겼다 돌아오면 leave가 여러 번 남는다)
        "SELECT v.name, count(*) visits, (SELECT sum(dwell_ms) FROM usage_events l WHERE l.type='leave' AND l.name=v.name AND l.ts >= ?) * 1.0 / count(*) avg_dwell_ms "
        "FROM usage_events v WHERE v.type='view' AND v.ts >= ? GROUP BY v.name ORDER BY visits DESC LIMIT 12", (since, since))]
    paths = [dict(r) for r in conn.execute(
        "SELECT ref, name, count(*) n FROM usage_events WHERE type='view' AND ts >= ? AND ref IS NOT NULL AND ref != name "
        "GROUP BY ref, name ORDER BY n DESC LIMIT 8", (since,))]
    actions = [dict(r) for r in conn.execute(
        "SELECT name, count(*) n FROM usage_events WHERE type='action' AND ts >= ? GROUP BY name ORDER BY n DESC", (since,))]
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    dropped = [r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM usage_events WHERE type='view' AND ts >= ? AND ts < ? AND name NOT IN "
        "(SELECT name FROM usage_events WHERE type='view' AND ts >= ?)", (month_ago, since, since))]
    sessions = conn.execute("SELECT count(DISTINCT session) FROM usage_events WHERE ts >= ?", (since,)).fetchone()[0]
    return {"since": first, "visits": sum(s["visits"] for s in screens), "sessions": sessions, "screens": screens, "paths": paths,
            "actions": actions, "dropped": dropped[:10]}


def value(conn, days: int = 7) -> dict:
    """효용 — P0는 시스템 판단 채점(발표 전 기대)과 생성물 열람(open 이벤트가 쌓이면). 열람률·👍/👎는 P1."""
    opens = [dict(r) for r in conn.execute(
        "SELECT name, count(*) n, count(DISTINCT entity) uniq FROM usage_events WHERE type='open' AND ts >= ? GROUP BY name",
        ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),))]
    grades = {"hit": 0, "underweighted": 0, "noise": 0, "missed": 0}
    for (m,) in conn.execute("SELECT meta_json FROM transcript_reactions WHERE meta_json IS NOT NULL"):
        meta = json.loads(m)
        for g in meta.get("grades") or []:
            if g.get("verdict") in grades:
                grades[g["verdict"]] += 1
        grades["missed"] += len(meta.get("missed") or [])
    return {"opens": opens, "expectation_grades": grades}


def summary(days: int = 7) -> dict:
    flush()
    conn = get_connection()
    try:
        from pipeline.health import report
        problems = [i for i in report(conn, launchd=False) if i["status"] != "ok"]
        ce = [dict(r) for r in conn.execute("SELECT endpoint, field, kind, count, last_seen FROM client_errors "
                                            "WHERE last_seen >= datetime('now', ?) ORDER BY last_seen DESC LIMIT 10", (f"-{days} days",))]
        return {"days": days, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "jobs": job_problems(conn, days), "api": api_health(conn, days), "client_errors": ce,
                "freshness": [{"label": i["label"], "detail": i["detail"] or i["status"]} for i in problems],
                "costs": costs(conn, days), "usage": usage(conn, days), "value": value(conn, days)}
    finally:
        conn.close()


# ---------- 즉시 경고 · 주간 리포트 ----------

def _conditions(conn) -> dict[str, str]:
    """지금 켜져 있어야 할 경고 — key → 문구."""
    out = {}
    for s in job_problems(conn, 3)["streaks"]:
        if s["streak"] >= 3:
            out[f"job_streak:{s['job']}"] = f"{s['name']} 연속 {s['streak']}회 실패 — {s['last'][:120]}"
    days = [r[0] or 0 for r in conn.execute(
        "SELECT sum(cost_usd) FROM llm_calls WHERE created_at >= datetime('now','-15 days') AND date(created_at,'+9 hours') < date('now','+9 hours') "
        "GROUP BY date(created_at,'+9 hours')")]
    today = conn.execute("SELECT coalesce(sum(cost_usd),0) FROM llm_calls WHERE date(created_at,'+9 hours') = date('now','+9 hours')").fetchone()[0]
    if len(days) >= 5:
        med = statistics.median(days)
        if today > max(5.0, med * 2):
            top = conn.execute("SELECT job, round(sum(cost_usd),2) FROM llm_calls WHERE date(created_at,'+9 hours') = date('now','+9 hours') "
                               "GROUP BY job ORDER BY 2 DESC LIMIT 1").fetchone()
            out["cost_spike"] = f"오늘 LLM ${today:.1f} — 평소(14일 중앙값 ${med:.1f})의 {today / med:.1f}배, 최대 {_name(top[0])} ${top[1]}"
    hour = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:00")
    r = conn.execute("SELECT sum(count), sum(CASE WHEN status_class='5xx' THEN count ELSE 0 END) FROM api_requests_hourly WHERE hour >= ?", (hour,)).fetchone()
    if r[0] and r[0] >= 20 and r[1] / r[0] > 0.05:
        out["api_5xx"] = f"최근 1시간 API 5xx {r[1]}/{r[0]}건({r[1] / r[0] * 100:.0f}%)"
    return out


def check_alerts(send=None, dry_run: bool = False) -> dict:
    """상태가 바뀔 때만 보낸다 — 새로 켜진 경고(같은 경고는 하루 1회)와 풀린 경고."""
    from pipeline.notify import send_telegram
    send = send or send_telegram
    conn = get_connection()
    try:
        now = _conditions(conn)
        prev = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM alert_state")}
        fired, resolved = [], []
        for k, text in now.items():
            p = prev.get(k)
            recently = p and p["sent_at"] and conn.execute("SELECT julianday('now') - julianday(?) < 1", (p["sent_at"],)).fetchone()[0]
            if not (p and p["active"]) or not recently:
                fired.append((k, text))
        for k, p in prev.items():
            if p["active"] and k not in now:
                resolved.append((k, p["detail"]))
        lines = [f"⚠️ {t}" for _, t in fired] + [f"✅ 해소: {t}" for _, t in resolved]
        sent = bool(lines) and (dry_run or send("🔭 <b>시스템 경고</b>\n" + "\n".join(lines)))
        for k, text in now.items():
            was_fired = any(k == f for f, _ in fired)
            conn.execute("INSERT INTO alert_state (key, active, detail, changed_at, sent_at) VALUES (?,1,?, datetime('now'), ?) "
                         "ON CONFLICT(key) DO UPDATE SET active=1, detail=excluded.detail, "
                         "changed_at=CASE WHEN alert_state.active=0 THEN datetime('now') ELSE alert_state.changed_at END, "
                         "sent_at=COALESCE(excluded.sent_at, alert_state.sent_at)",
                         (k, text, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if was_fired and sent and not dry_run else None))
        for k, _ in resolved:
            conn.execute("UPDATE alert_state SET active=0, changed_at=datetime('now') WHERE key=?", (k,))
        conn.commit()
        return {"active": list(now), "fired": [k for k, _ in fired], "resolved": [k for k, _ in resolved], "sent": bool(sent)}
    finally:
        conn.close()


def weekly_message(days: int = 7) -> str:
    s = summary(days)
    j, c, u, v = s["jobs"], s["costs"], s["usage"], s["value"]
    t = j["total"]
    rate = (t["ok"] / t["runs"] * 100) if t["runs"] else 0
    end = datetime.now(timezone.utc) + timedelta(hours=9)
    start = end - timedelta(days=days)
    L = [f"📊 <b>이번 주 시스템</b> ({start:%m/%d}~{end:%m/%d})", ""]
    L.append(f"<b>잘 도는가</b> 정기 작업 {rate:.1f}% 성공({t['runs']:,}회 · 오류 {t['err']} · 부분 {t['partial']})")
    todo: dict[str, list[str]] = {"streak": [], "fail": [], "chronic": [], "cost": []}
    for x in j["streaks"][:2]:
        L.append(f"· {x['name']} 연속 {x['streak']}회 실패")
        todo["streak"].append(f"{x['name']} 연속 실패 고치기")
    for x in j["failing"][:2]:
        L.append(f"· {x['name']} {x['n']}회 중 {x['err']}회 실패")
        todo["fail"].append(f"{x['name']} 실패 원인 확인")
    for x in j["chronic"][:2]:
        L.append(f"· {x['name']} 최근 5회 모두 부분 성공(만성)")
        todo["chronic"].append(f"{x['name']} 부분 실패 원인 확인")
    if s["api"]["requests"]:
        L.append(f"· API {s['api']['requests']:,}건 · 5xx {s['api']['errors_5xx']}건")
    if s["client_errors"]:
        L.append(f"· 화면 API 오류 {len(s['client_errors'])}종")
    L.append("")
    ch = f" (지난주 {'+' if (c['change_pct'] or 0) >= 0 else ''}{c['change_pct']}%)" if c["change_pct"] is not None else ""
    L.append(f"<b>얼마나 드는가</b> LLM ${c['usd']:.1f}{ch}")
    if c["by_job"]:
        L.append("· " + " · ".join(f"{x['name']} ${x['usd']:.1f}" + (f"({x['share']}%)" if i == 0 else "") for i, x in enumerate(c["by_job"][:3])))
        if c["by_job"][0]["share"] >= 40:
            todo["cost"].append(f"{c['by_job'][0]['name']} 비용({c['by_job'][0]['share']}%) 줄일지 검토")
    L.append("")
    if u["visits"]:
        L.append(f"<b>무엇을 쓰는가</b> 화면 방문 {u['visits']}회 · " + " · ".join(f"{x['name']} {x['visits']}회" for x in u["screens"][:3]))
        if u["actions"]:
            L.append("· 동작: " + " · ".join(f"{a['name']} {a['n']}" for a in u["actions"][:4]))
        if u["dropped"]:
            L.append("· 지난달엔 열었는데 이번 주 안 연 화면: " + " · ".join(u["dropped"][:4]))
    else:
        L.append("<b>무엇을 쓰는가</b> 사용 기록 수집 시작 — 다음 주부터 집계")
    L.append("")
    g = v["expectation_grades"]
    if sum(g.values()):
        L.append(f"<b>도움이 되는가</b> 발표 전 기대 채점: 맞힘 {g['hit']} · 덜 봄 {g['underweighted']} · 과하게 봄 {g['noise']} · 못 봄 {g['missed']}")
    # 할 일은 종류별로 하나씩 먼저(연속 실패 → 실패 → 만성 부분 성공 → 비용), 남는 칸은 나머지로
    picked = [v[0] for v in todo.values() if v]
    picked += [x for v in todo.values() for x in v[1:]]
    if picked:
        L += ["", "<b>이번 주 할 일</b>"] + [f"{i + 1}. {x}" for i, x in enumerate(picked[:3])]
    return "\n".join(L)

