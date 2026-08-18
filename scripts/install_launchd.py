"""cron → launchd 이전 설치기 (D-106).

왜 launchd인가 — 두 고질병이 같은 뿌리였다:
  ① cron은 GUI 로그인 세션 밖에서 돌아 **macOS 키체인에 접근하지 못한다**.
     claude CLI 자격증명이 키체인(`Claude Code-credentials`)에 있어 cron의 모든 LLM 호출이
     `Not logged in · Please run /login`으로 실패했다(로그 45,294건, 7/17~8/18).
     → enrich는 키워드 fallback, 유튜브 정리본은 failed 223/ok 116으로 고착.
  ② cron은 **놓친 스케줄을 재실행하지 않는다**. 08:00에 랩탑이 자고 있으면 그날 브리핑은 증발.
     평일 22일 중 발송 9일(41%)의 원인.

launchd user agent는 사용자 Aqua 세션에 적재되어 키체인이 열리고(①),
StartCalendarInterval·StartInterval은 기상 시 놓친 회차를 실행한다(②).

  python scripts/install_launchd.py           # 설치 + 부트스트랩
  python scripts/install_launchd.py --dry-run # plist 미리보기만
  python scripts/install_launchd.py --uninstall

롤백: --uninstall 후 `crontab scripts/crontab.legacy.bak`
"""
import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PY = str(PROJECT / ".venv" / "bin" / "python")
LOG = str(PROJECT / "logs" / "ingest.log")
AGENTS = Path.home() / "Library" / "LaunchAgents"
PREFIX = "dev.explorer."

# claude CLI(node)를 PATH에서 찾을 수 있어야 한다 — launchd는 로그인 셸 PATH를 물려주지 않는다.
# CLAUDE_BIN은 셸이 아니라 .env에 있으므로 직접 읽는다.
sys.path.insert(0, str(PROJECT / "backend"))
import config  # noqa: E402,F401 — load_dotenv 부수효과

_claude_bin = os.environ.get("CLAUDE_BIN", "")
_NODE_BIN = str(Path(_claude_bin).parent) if _claude_bin else ""
PATH = ":".join(p for p in [_NODE_BIN, "/opt/homebrew/bin", "/usr/local/bin",
                            "/usr/bin", "/bin", "/usr/sbin", "/sbin"] if p)

# (label, 실행 인자, 스케줄) — 스케줄은 int(초 간격) 또는 StartCalendarInterval dict/list
JOBS = [
    ("chain", [str(PROJECT / "scripts" / "run_chain.sh")], 1800),
    ("prices", [PY, "scripts/ingest_prices.py", "--daily"],
     [{"Weekday": d, "Hour": 16, "Minute": 10} for d in range(1, 6)]),
    ("krmovers", [PY, "scripts/snapshot_kr_movers.py"],          # D-108 — 신규진입 판정에 일별 필요
     [{"Weekday": d, "Hour": 16, "Minute": 20} for d in range(1, 6)]),
    ("briefing", [PY, "scripts/send_briefing.py"],
     [{"Weekday": d, "Hour": 8, "Minute": 0} for d in range(1, 6)]),
    ("promote", [PY, "scripts/promote_knowledge.py"], {"Weekday": 0, "Hour": 7, "Minute": 0}),
    ("contradictions", [PY, "scripts/scan_contradictions.py"], {"Hour": 6, "Minute": 45}),
    ("proposals", [PY, "scripts/scan_agent_proposals.py"], {"Weekday": 0, "Hour": 7, "Minute": 20}),
    ("questions", [PY, "scripts/refresh_questions.py"], {"Hour": 7, "Minute": 40}),
]


def build(label: str, argv: list[str], schedule) -> dict:
    d = {
        "Label": PREFIX + label,
        "ProgramArguments": argv,
        "WorkingDirectory": str(PROJECT),
        "EnvironmentVariables": {"PATH": PATH},
        "StandardOutPath": LOG,
        "StandardErrorPath": LOG,
    }
    if isinstance(schedule, int):
        d["StartInterval"] = schedule
    else:
        d["StartCalendarInterval"] = schedule
    return d


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()

    domain = f"gui/{os.getuid()}"
    AGENTS.mkdir(parents=True, exist_ok=True)
    rc = 0

    for label, argv, schedule in JOBS:
        full = PREFIX + label
        path = AGENTS / f"{full}.plist"

        if args.uninstall:
            _run("launchctl", "bootout", f"{domain}/{full}")
            path.unlink(missing_ok=True)
            print(f"[제거] {full}")
            continue

        data = build(label, argv, schedule)
        if args.dry_run:
            print(f"--- {path} ---")
            print(plistlib.dumps(data).decode())
            continue

        path.write_bytes(plistlib.dumps(data))
        _run("launchctl", "bootout", f"{domain}/{full}")   # 기존분 있으면 교체
        p = _run("launchctl", "bootstrap", domain, str(path))
        if p.returncode != 0:
            print(f"[실패] {full} — {p.stderr.strip()}")
            rc = 1
        else:
            print(f"[설치] {full}")

    if args.uninstall or args.dry_run:
        return rc

    print("\n다음 단계: crontab에서 중복 등록을 제거해야 이중 실행이 안 납니다.")
    print("  crontab -l  # 현재 확인 (백업: scripts/crontab.legacy.bak)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
