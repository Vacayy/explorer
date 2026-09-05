#!/bin/bash
# 재태깅 백필 야간 창 실행기 (D-118) — launchd `dev.explorer.backfill`가 02:00에 호출.
#
# 왜 래퍼가 필요한가:
#  ① **중복 실행 방지** — 이미 돌고 있으면(수동 실행분 포함) 그대로 두고 빠진다.
#     두 프로세스가 같은 대상을 집으면 같은 문서를 두 번 태깅해 토큰을 버린다.
#  ② **데드라인 주입** — 04:00 이후엔 새 콜을 시작하지 않고 정상 종료(배치 커밋 후 탈출).
#  ③ launchd는 잠들어 있던 시각의 회차를 **기상 시 실행**하므로, 02:00에 자고 있었어도
#     깨는 즉시 시작된다(D-106). 그래서 "무조건 재개"가 성립한다.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

LOG="logs/backfill_enrich.log"
UNTIL="${BACKFILL_UNTIL:-04:00}"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# ⓪ 관리자 플래그 게이트(D-129) — launchd 잡은 등록해두되 플래그가 꺼져 있으면 아무것도 안 한다.
#    install_launchd.py를 다시 돌릴 때마다 중단해둔 백필이 되살아나던 함정을 없앤다.
#    재개는 플래그 한 번 켜기: ops.set_flag('backfill_enrich', True)
if ! ./.venv/bin/python -c "
import sys; sys.path.insert(0,'backend')
from pipeline.ops import flag_enabled
sys.exit(0 if flag_enabled('backfill_enrich', default=False) else 1)" 2>/dev/null; then
  echo "$(ts) [backfill] 플래그 off — 실행 안 함" >> "$LOG"
  exit 0
fi

# 인터프리터 경로로 시작하는 줄만 매칭 — 부분문자열이면 grep·에디터에도 걸린다(D-116 교훈)
if pgrep -f '^/.*[Pp]ython.*backfill_enrich_batch\.py' >/dev/null 2>&1; then
  echo "$(ts) [backfill] 이미 실행 중 — 이번 회차 skip" >> "$LOG"
  exit 0
fi

echo "$(ts) [backfill] 시작 (데드라인 $UNTIL)" >> "$LOG"
./.venv/bin/python -u scripts/backfill_enrich_batch.py --budget-calls 0 --until "$UNTIL" >> "$LOG" 2>&1
rc=$?
echo "$(ts) [backfill] 종료(rc=$rc)" >> "$LOG"
# 끊겨도 사실이 남게 — 결과 보고서 생성 (LLM 0). 아침에 사람이 한 번 읽으면 된다.
./.venv/bin/python scripts/backfill_report.py >> "$LOG" 2>&1
