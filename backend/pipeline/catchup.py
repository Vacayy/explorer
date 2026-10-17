"""정기 작업 따라잡기 — 들고 다니는 노트북을 서버로 쓰는 환경용 (D-249).

launchd는 잠든 동안 놓친 회차를 깨어날 때 **한 번** 실행한다(D-106). 그 한 번이 네트워크 없음·DB 잠금 등으로
실패하면 다음 정기 시각까지 아무도 다시 하지 않았다(2026-10-17 미국장 브리핑, 10-15·16 20:20 시세).

규칙(회차 = 가장 최근에 지난 정기 시각):
- 그 회차 이후 성공(`sched:<label>`이 ok/partial/skipped) 기록이 있으면 건너뛴다.
- 없으면 실행한다. 단 시도 사이 간격은 30분 × 지금까지 시도 수로 늘리고, 한 회차 최대 MAX_ATTEMPTS번.
- 오프라인이면 시도로 세지 않고 건너뛴다(이동 중).
- 늦으면 의미 없는 작업은 window_h 시간까지만 따라잡는다(아침 발송 등).
정기 시각의 launchd 실행과 30분 순회(`--catchup`)가 같은 판정을 거친다 — 이미 성공했으면 둘 다 건너뛴다.
이 모듈은 판정만 한다(순수 함수 + job_runs 읽기). 실행은 scripts/run_daily.py.
"""
from datetime import datetime, timedelta

MAX_ATTEMPTS = 8
BASE_GAP_MIN = 30
OK_STATUSES = ("ok", "partial", "skipped")


def last_due(schedule, now: datetime) -> datetime | None:
    """launchd StartCalendarInterval(dict 또는 list) 중 now 이전의 가장 최근 시각. Weekday 0·7=일요일."""
    entries = schedule if isinstance(schedule, list) else [schedule]
    best = None
    for back in range(0, 8):
        day = (now - timedelta(days=back)).date()
        wd = (day.weekday() + 1) % 7          # launchd: 0=일, 1=월 … 6=토
        for e in entries:
            if "Weekday" in e and e["Weekday"] % 7 != wd:
                continue
            at = datetime(day.year, day.month, day.day, e.get("Hour", 0), e.get("Minute", 0), tzinfo=now.tzinfo)
            if at <= now and (best is None or at > best):
                best = at
        if best is not None and best.date() == day:
            break
    return best


def decide(due: datetime | None, runs: list[tuple[str, datetime]], now: datetime,
           window_h: float | None = None) -> tuple[bool, str]:
    """runs = 이 작업의 (status, ran_at) 기록. 돌릴지와 이유를 돌려준다."""
    if due is None:
        return False, "정기 시각 없음"
    since = [(s, t) for s, t in runs if t >= due]
    if any(s in OK_STATUSES for s, _ in since):
        return False, f"{due:%m-%d %H:%M} 회차 이미 성공"
    if window_h is not None and now - due > timedelta(hours=window_h):
        return False, f"{due:%m-%d %H:%M} 회차는 {window_h:g}시간이 지나 따라잡지 않음"
    attempts = [t for s, t in since if s not in OK_STATUSES]
    if len(attempts) >= MAX_ATTEMPTS:
        return False, f"{due:%m-%d %H:%M} 회차 {MAX_ATTEMPTS}번 실패 — 다음 회차까지 멈춤"
    if attempts and now - max(attempts) < timedelta(minutes=BASE_GAP_MIN * len(attempts)):
        return False, f"직전 실패 뒤 대기 중({BASE_GAP_MIN * len(attempts)}분 간격)"
    return True, f"{due:%m-%d %H:%M} 회차 {'첫 실행' if not attempts else f'{len(attempts) + 1}번째 시도'}"


def online(host: str = "1.1.1.1", port: int = 443, timeout: float = 3.0) -> bool:
    import socket
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False
