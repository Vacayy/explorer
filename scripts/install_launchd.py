"""cron → launchd 이전 설치기 (D-106).

왜 launchd인가 — 두 고질병이 같은 뿌리였다:
  ① cron은 GUI 로그인 세션 밖에서 돌아 **macOS 키체인에 접근하지 못한다**.
     claude CLI 자격증명이 키체인(`Claude Code-credentials`)에 있어 cron의 모든 LLM 호출이
     `Not logged in · Please run /login`으로 실패했다(로그 45,294건, 7/17~8/18).
     → enrich는 키워드 fallback, 유튜브 정리본은 failed 223/ok 116으로 고착.
  ② cron은 **놓친 스케줄을 재실행하지 않는다**. 07:00에 랩탑이 자고 있으면 그날 브리핑은 증발.
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
import time
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
    # KRX 종가는 16:30에 확정 송출(네이버 closePriceSendTime) — 그 뒤에 수집. 감시(16:40)보다 앞.
    # 20:20 재실행은 시간외 단일가·NXT까지 끝난 뒤 같은 값을 덮어쓴다(D-220 — 16:35엔 marketStatus가 OPEN이라 판정에 안 씀).
    ("prices", [PY, "scripts/ingest_prices.py", "--daily"],
     [{"Weekday": d, "Hour": h, "Minute": m} for d in range(1, 6) for h, m in ((16, 35), (20, 20))]),
    # 발견용 시세 이력(D-177 저장소) 재게시 — 일별 시세 20:20 뒤. 전 종목 재수집 20~40분, 모델 호출 0 (D-220).
    ("history", [PY, "scripts/refresh_market_history.py"],
     [{"Weekday": d, "Hour": 20, "Minute": 40} for d in range(1, 6)]),
    # 시장 국면·리스크 지표(D-076) — 국내 마감 뒤. 문서엔 '권장'으로만 있고 등록이 빠져 9-10부터 한 달 묵었다(D-222 점검으로 발견).
    # 회사채 스프레드(D-230) — 미국 장 마감 뒤. 채권 데이터는 로컬 어댑터(git 제외)가 있을 때만, 없으면 skipped.
    ("credit", [PY, "scripts/collect_credit.py"], {"Hour": 7, "Minute": 30}),
    # 개인 투자 열기(D-231) — 협회 당일 집계 뒤. 한국거래소 개인 거래는 .env KRX_ID·KRX_PW 있을 때만.
    ("retail", [PY, "scripts/collect_retail.py"], [{"Weekday": d, "Hour": 18, "Minute": 30} for d in range(1, 6)]),
    ("market", [PY, "scripts/snapshot_market.py"],
     [{"Weekday": d, "Hour": 16, "Minute": 20} for d in range(1, 6)]),
    ("krmovers", [PY, "scripts/snapshot_kr_movers.py"],          # D-108 — 신규진입 판정에 일별 필요
     [{"Weekday": d, "Hour": 16, "Minute": 20} for d in range(1, 6)]),
    # 미국장 브리핑은 발송(07:00)보다 **먼저** 데워야 그날 것이 실린다 (D-112). 2026-09-09 발송 08:00→07:00(사용자 요청), 웜업도 06:30으로.
    # 매일 — 주말은 TradingView 값이 금요일과 같아 signature 캐시로 sonnet 0콜.
    ("usbriefing", [PY, "scripts/compute_briefing.py"], {"Hour": 6, "Minute": 30}),
    ("briefing", [PY, "scripts/send_briefing.py"],
     [{"Weekday": d, "Hour": 7, "Minute": 0} for d in range(1, 6)]),
    # 재태깅 백필 야간 창(D-118) — 02:00 시작, 스크립트가 04:00에 자진 종료.
    # 유휴 시간대라 주간 세션 사용량에 영향이 없고, 백로그가 비면 즉시 종료된다(대상 0건).
    ("backfill", [str(PROJECT / "scripts" / "run_backfill.sh")], {"Hour": 2, "Minute": 0}),
    # 내러티브 전량 배치는 **주 1회**(D-122) — 30분 체인엔 `--urgent`(신규·급증만)가 남는다.
    # 체인에서 전량을 돌리면 새 문서 1건에 해시가 바뀌어 opus가 재발화했다(실측 7일 52회·16.1시간).
    # promote(07:00)·proposals(07:20)보다 먼저 돌아 그 주의 서사가 지식 승격의 입력이 되게 06:00.
    ("narratives", [PY, "scripts/compute_narratives.py"], {"Weekday": 0, "Hour": 6, "Minute": 0}),
    # 축적물 백업(D-129) — DB VACUUM+gzip · vault tar · media 미러. 매일 04:30, 실측 20초.
    # 잠들어 있었으면 launchd가 기상 시 실행한다(D-106).
    ("backup", [PY, "scripts/backup.py"], {"Hour": 4, "Minute": 30}),
    ("promote", [PY, "scripts/promote_knowledge.py"], {"Weekday": 0, "Hour": 7, "Minute": 0}),
    ("contradictions", [PY, "scripts/scan_contradictions.py"], {"Hour": 6, "Minute": 45}),
    ("proposals", [PY, "scripts/scan_agent_proposals.py"], {"Weekday": 0, "Hour": 7, "Minute": 20}),
    ("questions", [PY, "scripts/refresh_questions.py"], {"Hour": 7, "Minute": 40}),
    # 수출입(D-140) — 매일 09:20 신선도 1콜: 원천 최신월이 적재분보다 앞서면 그때만 전체 수집(관세청 현행화 '15일경').
    ("trade", [PY, "scripts/collect_trade.py", "--if-fresh"], {"Hour": 9, "Minute": 20}),
    # 종목 묶음 감시(D-185) — 일별 시세(16:10) 뒤 평가. 모델 호출 0, 같은 기준일 재실행은 건너뛴다(멱등).
    ("watch", [PY, "scripts/evaluate_watch_rules.py"],
     [{"Weekday": d, "Hour": 16, "Minute": 40} for d in range(1, 6)]),
    # 포트폴리오 알림(D-214) — 장중 급등락·공시는 평일 09:00–18:00 30분마다, 요약·기술적 신호는 종가·감시 뒤 16:50.
    ("pfintraday", [PY, "scripts/portfolio_alerts.py", "--intraday"],
     [{"Weekday": d, "Hour": h, "Minute": m} for d in range(1, 6) for h in range(9, 18) for m in (0, 30)] +
     [{"Weekday": d, "Hour": 18, "Minute": 0} for d in range(1, 6)]),
    ("pfclose", [PY, "scripts/portfolio_alerts.py", "--close"],
     [{"Weekday": d, "Hour": 16, "Minute": 50} for d in range(1, 6)]),
    # 실적 발언 모멘텀(D-217) — 매일 SEC 8-K·AV 컨콜 수집·추출·판정(미국 장 마감 뒤 아침), 주간 알림은 월요일 브리핑 뒤.
    ("callmomentum", [PY, "scripts/call_momentum.py", "--daily"], {"Hour": 7, "Minute": 20}),
    ("callmomentumweekly", [PY, "scripts/call_momentum.py", "--weekly"], {"Weekday": 1, "Hour": 7, "Minute": 10}),
    # 국내 도시에 원천 — 종목 마스터·DART 공시·분기 재무(호출 예산 안에서 보유→관심→시총 상위 순)·밸류(PER·PBR).
    # 일별 시세 20:20 뒤라 밸류가 그날 종가 기준이 된다. 매일 — 주말엔 밸류가 '이미 있음'으로 건너뛰고 재무 백필만 이어간다.
    ("krcompany", [PY, "scripts/collect_kr_company_data.py"], {"Hour": 21, "Minute": 30}),
    # 따라잡기 순회(D-249) — 30분마다 아래 CATCHUP 작업 중 '지난 회차 성공 기록이 없는 것'만 다시 시도한다.
    ("catchup", [PY, "scripts/run_daily.py", "--catchup"], 1800),
]

# 따라잡기 대상(D-249, backend/pipeline/catchup.py) — launchd는 이 작업들을 scripts/run_daily.py <label>로 감싸 부른다.
# record: 스크립트가 스스로 남기는 job_runs 이름(종료코드 0이어도 그 기록이 error면 실패로 본다).
# window_h: 늦으면 의미 없는 작업은 정기 시각 뒤 이 시간까지만 따라잡는다. 없으면 다음 회차까지.
# 빠진 것: chain(30분 간격 자체), pfintraday(장중 30분 알림 — 지난 회차는 의미 없음), backfill(야간 기회 작업), catchup 자신.
CATCHUP = {
    "prices": {"record": "prices"},
    "history": {"record": "market_history"},
    "credit": {"record": "credit"},
    "retail": {"record": "retail"},
    "market": {"record": "snapshot_market"},
    "krmovers": {"record": "snapshot_kr_movers"},
    "usbriefing": {"record": "compute_briefing"},
    "briefing": {"window_h": 5},               # 아침 텔레그램 — 점심 넘어 보내면 의미가 없다
    "narratives": {"record": "compute_narratives"},
    "backup": {"record": "backup"},
    "promote": {"record": "promote_knowledge"},
    "contradictions": {},
    "proposals": {"record": "agent_proposals"},
    "questions": {"record": "refresh_questions"},
    "trade": {"record": "collect_trade"},
    "watch": {},
    "pfclose": {"window_h": 7},                # 종가 요약 — 그날 밤까지만
    "callmomentum": {},
    "callmomentumweekly": {"window_h": 24},
    "krcompany": {},
}


def build(label: str, argv: list[str], schedule) -> dict:
    if label in CATCHUP:      # 성공 기록 확인 → 실행 → sched:<label> 기록 (D-249)
        argv = [PY, str(PROJECT / "scripts" / "run_daily.py"), label]
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
        # bootout 직후 bootstrap은 잡이 아직 정리 중이면 'Input/output error'로 실패한다.
        # 실패한 채 두면 그 잡이 **등록 해제 상태로 남아** 스케줄이 조용히 멈춘다 — 반드시 재시도.
        for attempt in range(4):
            p = _run("launchctl", "bootstrap", domain, str(path))
            if p.returncode == 0:
                print(f"[설치] {full}")
                break
            time.sleep(1.5 * (attempt + 1))
        else:
            print(f"[실패] {full} — {p.stderr.strip() or p.stdout.strip()}")
            rc = 1

    if args.uninstall or args.dry_run:
        return rc

    print("\n다음 단계: crontab에서 중복 등록을 제거해야 이중 실행이 안 납니다.")
    print("  crontab -l  # 현재 확인 (백업: scripts/crontab.legacy.bak)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
