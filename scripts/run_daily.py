"""정기 작업 실행기 — 회차 성공 기록을 확인하고 필요할 때만 돌린다 (D-249, backend/pipeline/catchup.py).

  python scripts/run_daily.py <label>     # launchd 정기 시각 (install_launchd.CATCHUP 대상)
  python scripts/run_daily.py --catchup   # 30분 순회: 지난 회차를 아직 성공 못 한 작업만
  python scripts/run_daily.py --status    # 판정만 출력(실행 안 함)

각 실행은 job_runs에 `sched:<label>`로 남는다(ok/partial/skipped/error). 오프라인이면 기록 없이 건너뛴다.
"""
import fcntl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))
sys.path.insert(0, str(PROJECT / "scripts"))

from install_launchd import CATCHUP, JOBS  # noqa: E402
from database import get_connection  # noqa: E402
from pipeline.catchup import decide, last_due, online  # noqa: E402
from pipeline.ops import record_run  # noqa: E402

LOCKS = PROJECT / "logs" / "locks"
BY_LABEL = {label: (argv, schedule) for label, argv, schedule in JOBS}


def _utc(text: str) -> datetime:
    return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _runs(job: str, since: datetime) -> list[tuple[str, datetime]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT status, ran_at FROM job_runs WHERE job=? AND ran_at >= ?",
                            (job, since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
        return [(r["status"], _utc(r["ran_at"])) for r in rows]
    finally:
        conn.close()


def _judge(label: str, now: datetime):
    _, schedule = BY_LABEL[label]
    due = last_due(schedule, now)
    runs = _runs(f"sched:{label}", due) if due else []
    own = CATCHUP[label].get("record")
    if due and own:                          # 실행기 밖(수동 실행·버튼·도입 전 launchd)에서 성공한 것도 그 회차 성공으로 본다
        runs += _runs(own, due)
    return due, *decide(due, runs, now, CATCHUP[label].get("window_h"))


def run(label: str, now: datetime) -> str:
    due, should, why = _judge(label, now)
    if not should:
        return f"건너뜀 — {why}"
    if not online():
        return "건너뜀 — 오프라인(시도로 세지 않음)"
    LOCKS.mkdir(parents=True, exist_ok=True)
    lock = open(LOCKS / f"{label}.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return "건너뜀 — 이미 실행 중"
    started, t0 = datetime.now(timezone.utc), time.time()
    rc = subprocess.run(BY_LABEL[label][0], cwd=PROJECT).returncode
    status = "ok" if rc == 0 else "error"
    own = CATCHUP[label].get("record")
    if rc == 0 and own:                      # 종료코드 0이어도 스크립트 자신의 기록이 실패면 실패
        mine = sorted(_runs(own, started), key=lambda x: x[1])
        if mine and mine[-1][0] in ("error", "partial", "skipped"):
            status = mine[-1][0]
    record_run(f"sched:{label}", status, f"{why} · rc={rc}", int((time.time() - t0) * 1000))
    lock.close()
    return f"{status} — {why}"


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else "--status"
    now = datetime.now().astimezone()
    if arg in ("--catchup", "--status"):
        for label in CATCHUP:
            if arg == "--status":
                due, should, why = _judge(label, now)
                print(f"{label:20} {'실행 대상' if should else '-':6} {why}")
            else:
                due, should, why = _judge(label, now)
                if should:
                    print(f"[catchup] {label}: {run(label, now)}", flush=True)
        return 0
    if arg not in CATCHUP:
        print(f"알 수 없는 작업: {arg}")
        return 2
    print(f"[sched] {arg}: {run(arg, now)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
