# 배포·이식 런북 (클라우드/다른 로컬로 옮길 때)

> 2026-07-18. 목적: crontab·경로·권한처럼 **git 밖에 있거나 머신마다 다른 것**을 재현하기 위한 기록.
> 코드/DB 스키마 현행은 SYSTEM.md, 결정 이력은 DECISIONS.md. 자동화 겹침 방지는 D-024.

---

## 1. 사전 준비 (새 머신)

1. 저장소 클론. 프로젝트 루트를 `$PROJECT`라 하자 (예: `/opt/explorer`, `/Users/me/explorer`).
2. **Python 가상환경**: 루트에 `.venv` (관례 — 모든 스크립트가 `./.venv/bin/python` 가정).
   `python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt` (또는 기존 의존성).
3. **`.env`** (backend/.env): `DART_API_KEY` · `ENRICH_ENGINE=claude-code` · `CLAUDE_BIN`(claude CLI 절대경로) (+선택: `VAULT_PATH`·`MEDIA_PATH`·`RAG_MODEL`·`NARRATIVE_MODEL`·`ANTHROPIC_API_KEY`). API 키 주면 API 모드로 자동 전환.
4. **DB**: `backend/db/stock_explorer.db` (SQLite, WAL). 이식 = 이 파일 복사(리프트&시프트) 또는 시딩 스크립트 재실행(`seed_companies`·`seed_entities`·`seed_sectors` 등, SYSTEM.md §5-3).
5. `logs/` 디렉토리 존재 확인(`mkdir -p logs`).

## 2. 자동화 (cron)

수집·계산은 cron이 구동. **30분 체인은 `scripts/run_chain.sh` 래퍼**로 돌리며 겹침 방지 락을 포함한다(D-024 — 한 사이클이 30분을 넘겨도 다음 회차가 위에 쌓이지 않게 skip).

### 2-1. run_chain.sh — 이식 시 이 형태여야 함 (경로 자동 도출)
> ⚠️ 현재 이 리포의 로컬 run_chain.sh는 프로젝트 경로가 **하드코딩**돼 있다(생성 후 macOS App-Management 보호가 걸려 이 머신에선 수정 불가). **이식 대상에서는 아래 이식성 버전으로 교체**하라 — 스크립트 위치에서 경로를 도출해 무수정 동작한다.

```bash
#!/bin/bash
# 30분 수집 체인 — 겹침 방지 락 (D-024). flock은 macOS 미포함이라 mkdir+PID로 구현.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1
LOCK="/tmp/explorer_chain$(echo "$PROJECT_DIR" | tr '/' '_').lock"
PY="./.venv/bin/python"
LOG="logs/ingest.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

if ! mkdir "$LOCK" 2>/dev/null; then
  OLDPID=$(cat "$LOCK/pid" 2>/dev/null || echo "")
  if [ -n "$OLDPID" ] && kill -0 "$OLDPID" 2>/dev/null; then
    echo "$(ts) [chain] 이전 실행(pid $OLDPID) 진행 중 — skip" >> "$LOG"; exit 0
  fi
  echo "$(ts) [chain] stale 락 회수" >> "$LOG"; rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || exit 0
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

if pgrep -f 'scripts/ingest.py' >/dev/null 2>&1; then
  echo "$(ts) [chain] 래퍼 밖 수집 감지 — skip" >> "$LOG"; exit 0
fi

echo "$(ts) [chain] 시작" >> "$LOG"
$PY scripts/ingest.py            >> "$LOG" 2>&1 && \
$PY scripts/redigest_youtube.py  >> "$LOG" 2>&1 && \
$PY scripts/compute_signals.py   >> "$LOG" 2>&1 && \
$PY scripts/compute_narratives.py >> "$LOG" 2>&1 && \
$PY scripts/extract_events.py    >> "$LOG" 2>&1 && \
$PY scripts/scan_actions.py      >> "$LOG" 2>&1 && \
$PY scripts/compute_digests.py   >> "$LOG" 2>&1 && \
$PY scripts/vault_sync.py --export >> "$LOG" 2>&1 && \
$PY scripts/build_search_index.py >> "$LOG" 2>&1
echo "$(ts) [chain] 종료(rc=$?)" >> "$LOG"
```
`chmod +x scripts/run_chain.sh` 필수.

### 2-2. crontab 항목 (`$PROJECT`를 실제 절대경로로 치환)
```cron
# 30분 수집 체인 (겹침 방지 래퍼)
*/30 * * * * $PROJECT/scripts/run_chain.sh >> $PROJECT/logs/ingest.log 2>&1
# 평일 16:10 전종목 주가
10 16 * * 1-5 cd $PROJECT && ./.venv/bin/python scripts/ingest_prices.py --daily >> logs/ingest.log 2>&1
# 평일 08:00 아침 브리핑
0 8 * * 1-5 cd $PROJECT && ./.venv/bin/python scripts/send_briefing.py >> logs/ingest.log 2>&1
# 일요일 07:00 지식 주간 승격
0 7 * * 0 cd $PROJECT && ./.venv/bin/python scripts/promote_knowledge.py >> logs/ingest.log 2>&1
# 매일 06:45 모순 감지
45 6 * * * cd $PROJECT && ./.venv/bin/python scripts/scan_contradictions.py >> logs/ingest.log 2>&1
```
설치: 위를 파일로 저장 후 `crontab <파일>`. 확인: `crontab -l`.

## 3. macOS 권한 함정 (2026-07-17 실측 — Linux 클라우드는 해당 없음)

macOS에서 겪은 것들. **Linux 서버로 이식하면 대부분 사라진다.**

1. **crontab 쓰기가 멈춤(hang)**: `crontab <file>`/`crontab -`가 응답 없이 멈춤. cron 접근에 TCC 권한이 필요 — **시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한**에 실행 터미널/cron을 추가하면 해결. 짧은 경로에서 실행(긴 파일 경로는 crontab이 인자를 ~63자에서 잘라먹음).
2. **Desktop 하위 파일 보호**: `~/Desktop/**`은 TCC 보호 위치. 실행된 스크립트에 `com.apple.provenance`가 붙고 App-Management 보호가 걸리면 그 파일은 이후 **수정·삭제가 EPERM**(전체 디스크 접근으로도 애먹음). → 프로젝트를 Desktop 밖(예: `~/dev/`, `/opt/`)에 두면 회피. run_chain.sh를 못 고치면 이름을 바꿔 새로 만들고 crontab을 그쪽으로.
3. **flock 없음**: run_chain.sh가 mkdir+PID 락으로 대체(위).

## 4. 서버(24/7) 이식 메모
- SYSTEM.md §8: EC2+SQLite 리프트&시프트로 논의됨. DB 파일 1개 + `.venv` + `.env` + crontab이면 재현.
- Linux에선 flock 사용 가능 → run_chain.sh 락을 `flock -n /tmp/explorer.lock -c '...'`로 단순화해도 됨(선택).
- 시간대: cron은 서버 로컬 TZ 기준. KST 가정한 시각(16:10 등)은 서버 TZ를 Asia/Seoul로 두거나 UTC로 환산.
- 실행 서비스(FastAPI): `cd backend && ../.venv/bin/uvicorn main:app --port 8000` (SYSTEM.md §7). 프로세스 관리자(systemd/supervisor)로 상주화.

## 5. 검증 (이식 후)
- `crontab -l`에 5개 항목 · `bash scripts/run_chain.sh` 수동 1회 → `logs/ingest.log`에 `[chain] 시작`/`종료`.
- 두 번 연속 실행 시 두 번째가 `skip` 로그 남기는지(락 동작 확인).
- `./.venv/bin/python -c "from main import app"` (backend import) · `cd frontend && npm run build`.
