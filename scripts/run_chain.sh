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
if pgrep -f 'scripts/ingest.py' >/dev/null 2>&1; then
  echo "$(ts) [chain] 래퍼 밖 수집 프로세스 감지 — 이번 회차 skip" >> "$LOG"
  exit 0
fi

echo "$(ts) [chain] 시작" >> "$LOG"

# --- 수집보다 먼저: 값싸고 빠른 운영 점검 (수집 실패에 발목 잡히지 않도록 && 밖) ---
$PY scripts/probe_llm.py                     >> "$LOG" 2>&1   # LLM 엔진 생사 (D-106)
$PY scripts/send_briefing.py --catch-up      >> "$LOG" 2>&1   # 미발송 브리핑 보전 (D-106)

# 기존 crontab의 && 의미 보존 (한 단계 실패 시 이후 중단)
# redigest_youtube 제거(D-115) — 구독 채널 신규 영상 전부를 opus로 정리하면 아무도 안 읽는
# 영상까지 값을 치른다. 정리는 문서를 열 때만(spine_doc lazy / 텔레그램 액션).
$PY scripts/ingest.py            >> "$LOG" 2>&1 && \
$PY scripts/extract_doc_causal.py --limit 10 >> "$LOG" 2>&1 && \
$PY scripts/compute_signals.py   >> "$LOG" 2>&1 && \
$PY scripts/compute_narratives.py >> "$LOG" 2>&1 && \
$PY scripts/extract_events.py --limit 40 >> "$LOG" 2>&1 && \
$PY scripts/scan_actions.py      >> "$LOG" 2>&1 && \
$PY scripts/compute_digests.py   >> "$LOG" 2>&1 && \
$PY scripts/vault_sync.py --export >> "$LOG" 2>&1 && \
$PY scripts/build_search_index.py >> "$LOG" 2>&1
echo "$(ts) [chain] 종료(rc=$?)" >> "$LOG"
