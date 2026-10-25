#!/bin/bash
# 30분 수집 체인 — 겹침 방지 락 포함 (D-024).
#
# cron이 30분마다 호출하지만 한 사이클이 30분을 넘기면 다음 회차가 이전 회차 위에
# 쌓여(overlap) 두 개의 writer가 SQLite를 동시에 두드린다 → busy_timeout 경합·락.
# 이 래퍼는 이전 실행이 진행 중이면 이번 회차를 조용히 skip 한다 (stacking 방지).
# flock은 macOS 기본 미포함이라 mkdir 원자성 + PID 생존확인으로 이식성 있게 구현.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

LOCK="/tmp/explorer_chain.lock"
PY="./.venv/bin/python"
LOG="logs/ingest.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# --- 겹침 방지 락 ---
if ! mkdir "$LOCK" 2>/dev/null; then
  OLDPID=$(cat "$LOCK/pid" 2>/dev/null || echo "")
  if [ -n "$OLDPID" ] && kill -0 "$OLDPID" 2>/dev/null; then
    echo "$(ts) [chain] 이전 실행(pid $OLDPID) 진행 중 — 이번 회차 skip" >> "$LOG"
    exit 0
  fi
  echo "$(ts) [chain] stale 락 회수(pid ${OLDPID:-none})" >> "$LOG"
  rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || exit 0
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

# --- 전환기·수동 실행 대비: 래퍼 밖에서 이미 도는 수집이 있으면 skip ---
# 인터프리터 경로로 시작하는 줄만 매칭한다(D-116). 단순 부분문자열이면 이 문자열을 담은
# 아무 명령(grep·편집기·진단 스크립트)에도 걸려 **수집 회차를 조용히 건너뛴다** — 실측으로 확인됨.
if pgrep -f '^/.*[Pp]ython.*scripts/ingest\.py' >/dev/null 2>&1; then
  echo "$(ts) [chain] 래퍼 밖 수집 프로세스 감지 — 이번 회차 skip" >> "$LOG"
  exit 0
fi

echo "$(ts) [chain] 시작" >> "$LOG"

# 단계마다 독립 실행하고 실패한 단계를 모아 job_runs('chain')에 남긴다.
# 예전엔 && 연결이라 한 단계가 죽으면 뒤 단계가 조용히 건너뛰어졌고(DART 장애 때 다이제스트·검색 인덱스까지),
# 마지막 줄 `rc=$?`도 $(ts)가 먼저 돌아 늘 0이었다(10-16 07:24 전 단계 'database is locked'에도 rc=0).
# 각 단계는 멱등이라 앞 단계 실패 뒤에 돌아도 같은 데이터를 다시 처리할 뿐이다.
FAILED=()
STEPS=0
step() {
  local name="$1"; shift
  STEPS=$((STEPS + 1))
  "$PY" "$@" >> "$LOG" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    FAILED+=("$name(rc=$rc)")
    echo "$(ts) [chain] $name 실패 rc=$rc" >> "$LOG"
  fi
}

# --- 수집보다 먼저: 값싸고 빠른 운영 점검 ---
step probe_llm          scripts/probe_llm.py                 # LLM 엔진 생사 (D-106)
step briefing_catchup   scripts/send_briefing.py --catch-up  # 미발송 브리핑 보전 (D-106)
step macro_news         scripts/fetch_macro_news.py          # 미국 매체·Fed 헤드라인 (D-206)

# redigest_youtube 제거(D-115) — 구독 채널 신규 영상 전부를 opus로 정리하면 아무도 안 읽는
# 영상까지 값을 치른다. 정리는 문서를 열 때만(spine_doc lazy / 텔레그램 액션).
step ingest             scripts/ingest.py
step extract_doc_causal scripts/extract_doc_causal.py --limit 10
step compute_signals    scripts/compute_signals.py
step compute_narratives scripts/compute_narratives.py --urgent
step extract_events     scripts/extract_events.py --limit 40
step backfill_images    scripts/backfill_images.py --calls 200 --minutes 8   # 이미지 해석 백로그 — 켜져 있을 때 조금씩 (image-reading §9)
step scan_actions       scripts/scan_actions.py
step compute_digests    scripts/compute_digests.py
step vault_sync         scripts/vault_sync.py --export
step build_search_index scripts/build_search_index.py

if [ ${#FAILED[@]} -eq 0 ]; then STATUS=ok
elif [ ${#FAILED[@]} -eq "$STEPS" ]; then STATUS=error
else STATUS=partial; fi
SUMMARY="단계 ${STEPS}개 중 실패 ${#FAILED[@]}개${FAILED[*]:+: ${FAILED[*]}}"
"$PY" -c 'import sys; sys.path.insert(0, "backend"); from pipeline.ops import record_run; record_run("chain", sys.argv[1], sys.argv[2])' \
  "$STATUS" "$SUMMARY" >> "$LOG" 2>&1 || echo "$(ts) [chain] job_runs 기록 실패" >> "$LOG"
echo "$(ts) [chain] 종료 $STATUS — $SUMMARY" >> "$LOG"
