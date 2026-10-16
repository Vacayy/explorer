"""데이터 신선도 점검 (D-222, docs/specs/ops-health.md). LLM 0, 읽기 전용.

배경: 작업은 종료 코드 0으로 끝나도 결과가 비어 있을 수 있다 — 일별 시세가 105종목만 넣고(10-12·13),
발견용 이력이 4주 묵고(9-18), 시장 국면은 스케줄 없이 한 달 멈췄는데 아무 화면도 말하지 않았다.
그래서 작업이 아니라 **결과 데이터의 최신 시점**을 기대치와 비교한다.

- trading: 국내 장 마감 데이터. 기대 시점 = KOSPI 지수 일봉(index_kospi)으로 확인된 최근 거래일
  (오늘이면 마감 처리 시각 `ready` 뒤에만). 확인된 거래일만 세므로 휴장일·대체공휴일 오탐이 없다.
  지수 달력 자체가 묵는 것은 `indices` 항목이 잡는다.
- age: 시간 단위 최대 경과. 노트북 수면으로 밀린 실행도 launchd가 깨어나 따라잡으므로 여유를 둔다.
- launchd: 등록된 dev.explorer.* 중 마지막 종료 코드가 0이 아닌 것.
critical=True만 홈 브리핑·텔레그램 경고에 올리고, 나머지는 관리자 화면에만 보인다.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
HISTORY_DB = Path(__file__).resolve().parent.parent / "db" / "market_history.sqlite"

# (key, 라벨, 종류, 최신 시점 SQL, 기준, 채우는 곳, critical)
#   trading → 기준 = 마감 처리 완료 시각 "HHMM" (KST) · age → 기준 = 최대 경과 시간(h)
#   age의 SQL 값은 UTC 'YYYY-MM-DD HH:MM:SS' 또는 날짜(그날 KST 자정으로 간주)
CHECKS: list[tuple[str, str, str, str, object, str, bool]] = [
    ("prices", "국내 일별 시세", "trading", "SELECT max(trade_date) FROM stock_prices", "1730",
     "launchd prices 평일 16:35·20:20", True),
    ("market_history", "발견용 시세 이력", "trading", "HISTORY", "2130",
     "launchd history 평일 20:40", True),
    ("regime", "시장 국면 지표", "trading",
     "SELECT max(snapshot_date) FROM market_indicators WHERE indicator IN ('vix','kospi','fear_greed')", "1730",
     "launchd market 평일 16:20", True),
    ("risk", "리스크 지표", "trading",
     "SELECT max(snapshot_date) FROM market_indicators WHERE indicator LIKE 'risk\\_%' ESCAPE '\\' "
     "AND indicator NOT LIKE 'risk\\_sync%' ESCAPE '\\'", "1730",
     "launchd market 평일 16:20 · 홈 Risk 갱신 버튼", False),
    ("watch", "종목 묶음 감시", "trading", "SELECT max(as_of) FROM watch_evaluations", "1730",
     "launchd watch 평일 16:40", False),
    ("krmovers", "거래대금 상위", "trading", "SELECT max(trade_date) FROM kr_movers", "1730",
     "launchd krmovers 평일 16:20", False),
    ("documents", "피드 문서 유입", "age",
     "SELECT max(fetched_at) FROM raw_documents WHERE source_type IN ('telegram','blog','youtube')", 12,
     "launchd chain 30분 · ingest", True),
    ("chain", "30분 체인", "age", "SELECT max(ran_at) FROM job_runs WHERE job='compute_digests' AND status='ok'", 12,
     "launchd chain 30분", False),
    ("indices", "주요 지수(거래일 달력)", "age",
     "SELECT max(snapshot_date) FROM market_indicators WHERE indicator='index_kospi'", 100,
     "launchd usbriefing 06:30 · 홈 방문", True),
    ("macro", "매크로 지표", "age",
     "SELECT max(snapshot_date) FROM market_indicators WHERE indicator='macro_usdkrw'", 100,
     "launchd usbriefing 06:30 · 홈 갱신 버튼", False),
    ("us_briefing", "미국장 브리핑", "age", "SELECT max(created_at) FROM us_briefings", 100,
     "launchd usbriefing 06:30", False),
    ("retail", "개인 투자 열기(신용융자·예탁금)", "trading", "SELECT max(date) FROM retail_flows WHERE credit_total IS NOT NULL", "2400",   # 협회는 다음 날 게시 — 어제까지 기대
     "launchd retail 평일 18:30", False),
    ("credit", "회사채 스프레드", "age", "SELECT max(date) FROM credit_quotes", 100,
     "launchd credit 07:30 (로컬 어댑터)", False),
    ("backup", "DB 백업", "age", "SELECT max(ran_at) FROM job_runs WHERE job='backup' AND status='ok'", 36,
     "launchd backup 04:30", False),
]


def _now_kst(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(KST)


def expected_trading_day(conn: sqlite3.Connection, ready: str, now: datetime | None = None) -> str | None:
    """마감 처리가 끝났어야 할 가장 최근 확인 거래일."""
    kst = _now_kst(now)
    today = kst.date().isoformat()
    bound = today if kst.strftime("%H%M") >= ready else (kst.date() - timedelta(days=1)).isoformat()
    row = conn.execute("SELECT max(snapshot_date) FROM market_indicators WHERE indicator='index_kospi' "
                       "AND snapshot_date <= ?", (bound,)).fetchone()
    return row[0] if row else None


def trading_lag(conn: sqlite3.Connection, latest: str | None, expected: str | None) -> int:
    """latest 이후 expected까지 확인된 거래일 수 (0이면 최신)."""
    if not expected:
        return 0
    return conn.execute("SELECT count(DISTINCT snapshot_date) FROM market_indicators WHERE indicator='index_kospi' "
                        "AND snapshot_date > ? AND snapshot_date <= ?", (latest or "", expected)).fetchone()[0]


def _history_as_of() -> str | None:
    if not HISTORY_DB.exists():
        return None
    with sqlite3.connect(HISTORY_DB.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM metadata WHERE key='as_of'").fetchone()
    return json.loads(row[0]) if row else None


def _age_hours(value: str, now: datetime | None) -> float:
    if len(value) == 10:
        at = datetime.fromisoformat(value).replace(tzinfo=KST)
    else:
        at = datetime.fromisoformat(value[:19].replace("T", " "))
        at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
    return ((now or datetime.now(timezone.utc)) - at).total_seconds() / 3600


def price_coverage(conn: sqlite3.Connection, day: str) -> tuple[int, int, int]:
    """그날 저장 종목 수, 직전 5거래일 중앙값, 그날 시가총액 보유 종목 수."""
    count, caps = conn.execute("SELECT count(*), count(market_cap) FROM stock_prices WHERE trade_date=?", (day,)).fetchone()
    prior = sorted(r[0] for r in conn.execute(
        "SELECT count(*) FROM stock_prices WHERE trade_date < ? GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5", (day,)))
    return count, prior[len(prior) // 2] if prior else 0, caps


def launchd_failures() -> list[str]:
    """마지막 종료 코드가 0이 아닌 dev.explorer.* (launchctl 없으면 빈 목록)."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
    except Exception:  # noqa: BLE001 — 점검 보조 신호, 없으면 생략
        return []
    failed = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith("dev.explorer.") and parts[1] not in ("0", "-"):
            failed.append(f"{parts[2].removeprefix('dev.explorer.')}(종료 {parts[1]})")
    return failed


def report(conn: sqlite3.Connection, now: datetime | None = None, launchd: bool = True) -> list[dict]:
    items = []
    for key, label, kind, sql, limit, owner, critical in CHECKS:
        item = {"key": key, "label": label, "kind": kind, "owner": owner, "critical": critical,
                "latest": None, "expected": None, "status": "ok", "detail": ""}
        try:
            latest = _history_as_of() if sql == "HISTORY" else conn.execute(sql).fetchone()[0]
        except sqlite3.Error as exc:
            item.update(status="error", detail=f"조회 실패: {exc}"[:200])
            items.append(item)
            continue
        item["latest"] = latest
        if kind == "trading":
            expected = expected_trading_day(conn, str(limit), now)
            lag = trading_lag(conn, latest, expected)
            item["expected"] = expected
            if latest is None:
                item.update(status="stale", detail="저장된 데이터 없음")
            elif lag:
                item.update(status="stale", detail=f"{lag}거래일 지연")
            if key == "prices" and latest and item["status"] == "ok":
                count, usual, caps = price_coverage(conn, latest)
                if usual and count < usual * 0.9:
                    item.update(status="stale", detail=f"{latest} 저장 {count:,}종목 · 평소 {usual:,}종목")
                elif count and caps < count * 0.9:  # 시총이 비면 발견의 시총 표시·조건이 무너진다(10-12·13 사례)
                    item.update(status="stale", detail=f"{latest} 시가총액 {caps:,}/{count:,}종목만 보유")
        else:
            item["expected"] = f"{limit}시간 이내"
            if latest is None:
                item.update(status="stale", detail="저장된 데이터 없음")
            else:
                hours = _age_hours(str(latest), now)
                if hours > float(limit):
                    item.update(status="stale", detail=f"{hours / 24:.1f}일 전" if hours >= 48 else f"{hours:.0f}시간 전")
        items.append(item)
    if not launchd:
        return items
    failed = launchd_failures()
    items.append({"key": "launchd", "label": "예약 작업 종료 코드", "kind": "launchd", "owner": "launchctl list",
                  "critical": False, "latest": None, "expected": "모두 0",
                  "status": "stale" if failed else "ok", "detail": ", ".join(failed)})
    return items


def alerts(items: list[dict]) -> list[str]:
    """홈·텔레그램 경고용 — critical 중 정상이 아닌 항목 한 줄씩."""
    return [f"{i['label']} {i['detail'] or i['status']}" for i in items if i["critical"] and i["status"] != "ok"]


def alert_line(conn: sqlite3.Connection) -> str | None:
    """홈 방문마다 불리므로 launchctl은 부르지 않는다(비중요 항목이라 경고에 안 오름)."""
    found = alerts(report(conn, launchd=False))
    return " · ".join(found) if found else None
