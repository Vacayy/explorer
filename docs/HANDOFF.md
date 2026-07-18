# HANDOFF — 세션 인계 & 환경 이전 (2026-07-18)

> 왜 이 문서: 프로젝트가 `~/Desktop` 아래라 macOS TCC가 Bash의 프로젝트 접근을 막아
> (crontab 설치 hang, run_chain.sh 수정 불가, python/git 실행 불가) 검증·자동화가 막혔다.
> 해결 = **프로젝트를 Desktop 밖으로 이동**. 이 문서는 이동 절차 + 새 Claude Code 세션이
> 작업을 정확히 이어받는 법. (배포 일반은 DEPLOYMENT.md, 결정 이력은 DECISIONS.md)

---

## 0. 두 가지 두려움 — 둘 다 안 날아간다

- **DB**: `backend/db/stock_explorer.db`(+`-wal`·`-shm`)는 프로젝트 폴더 안의 파일이다. 폴더를 `mv`로 옮기면 내용 그대로 따라온다. 게다가 아래 절차는 **이동 전 백업**을 먼저 뜬다 → 이중 안전. 데이터 손실 0.
- **작업 기록·계획**: 내 세션 머릿속이 아니라 **전부 리포 문서에 적혀 있다**(Context Discipline). SYSTEM.md(현행 구조)·DECISIONS.md(D-022·23·24)·docs/specs/*(기획)·이 문서. 폴더와 함께 이동하므로 새 세션이 이 문서들을 읽으면 100% 이어받는다. (주의: `~/.claude`의 자동 메모리는 프로젝트 *경로*로 키가 걸려 있어 새 경로 세션엔 안 실릴 수 있음 → 그래서 리포 문서가 진짜 기억이다.)

## 1. 이동 절차 (Desktop → Desktop 밖)

새 위치 예: `~/dev/explorer` (또는 `~/explorer`, `/opt/explorer`). **Desktop·Documents·Downloads는 피할 것**(전부 TCC 보호).

```bash
# 0) (안전망) DB + 프로젝트 백업 — 이동 전에
mkdir -p ~/explorer-backup
cp backend/db/stock_explorer.db*  ~/explorer-backup/     # .db·-wal·-shm 3개 함께
#   (여유 있으면 폴더 통째로: cp -R ~/Desktop/projects/personal/explorer ~/explorer-backup/explorer-copy )

# 1) 이동 (폴더 통째로 — DB·코드·docs·.env 전부 따라옴)
mkdir -p ~/dev
mv ~/Desktop/projects/personal/explorer ~/dev/explorer

# 2) .venv 재생성 (가상환경엔 절대경로가 박혀 이동만으론 깨짐)
cd ~/dev/explorer
rm -rf .venv
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt   # requirements 없으면 기존 설치 방식대로
```

`.env`·`vault/`·`media/`·`logs/`·DB는 파일이라 그대로 따라온다. `.venv`만 재생성 대상.

## 2. run_chain.sh 교체 (이동 후엔 수정 가능)

Desktop에서 걸린 App-Management 보호가 새 위치엔 없다. `scripts/run_chain.sh`를
**경로 자동도출 버전**으로 교체(내용은 DEPLOYMENT.md §2-1 전문). 핵심은 하드코딩 경로를
`PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"`로 바꾸는 것.
`chmod +x scripts/run_chain.sh`.

## 3. crontab 설치

DEPLOYMENT.md §2-2의 5개 항목에서 `$PROJECT`를 `~/dev/explorer` 절대경로로 치환해 파일로
저장 후 `crontab <파일>`. (Desktop 밖이면 hang 없이 설치될 것 — 그래도 막히면 시스템 설정 →
개인정보 보호 → 전체 디스크 접근에 터미널/Claude Code 추가.) 확인 `crontab -l`.

## 4. 새 세션 점검 체크리스트 (이동 직후)

```bash
cd ~/dev/explorer
./.venv/bin/python -c "from database import get_connection as g; c=g(); \
  print('raw_docs', c.execute('select count(*) from raw_documents').fetchone()[0]); \
  print('narratives', c.execute('select count(*) from narratives').fetchone()[0]); \
  print('causal_edges', c.execute(\"select count(*) from entity_relations where rel_type in ('CAUSES','BENEFITS_FROM')\").fetchone()[0])"
#   기대치(2026-07-18 기준): raw_docs ~2150+, narratives 7, causal_edges 5 (AI v2)
cd backend && ../.venv/bin/python -c "from main import app; print('backend OK')"
cd ../frontend && npm run build   # tsc+vite 통과
bash scripts/run_chain.sh          # 수동 1회 → logs/ingest.log 에 [chain] 시작/종료
```
DB 수치가 위 기대치 근처면 데이터 온전. backend import·build 통과면 코드 온전.

## 5. 현재 작업 상태 (무엇이 됐고 / 무엇이 남았나)

### 완료 (커밋되어 있음 / 리포에 반영)
- **지식 페이지 개편** (D-022) — salience×conviction, 반증-우선 주입, /knowledge 3섹션. 구현 완료.
- **내러티브 인과 그래프 Phase 1** (D-023, docs/specs/narrative-causal-phase1.md=구현완료) —
  `narratives` 테이블(버전), macro·policy·event 노드, `CAUSES`/`BENEFITS_FROM` 엣지(+시간 스탬프),
  category, /narrative·/causal·/versions API, 프론트 인과 체인 뷰. 검증까지 끝남.
- **cron 겹침 방지** (D-024) — `scripts/run_chain.sh`(mkdir+PID 락). **작성·검증됨. 단 crontab 설치는 미완**(위 §3).

### 남은 일 (우선순위 순)
1. **crontab 설치** (§3) — locked run_chain.sh로 전환. 이게 되면 겹침 멈추고 파이프라인에 유휴 창 생김.
2. **refill (선택)** — 인과 엣지 0인 내러티브(HBM·Web3·지정학·엔터·지배구조·파운드리)를 채우기.
   *잠긴 cron이 돌면 `compute_narratives`가 상위 주제를 재생성하며 자연히 채워짐* → 급하지 않으면 방치 가능.
   즉시 채우려면(파이프라인 유휴 시): 각 주제의 `narratives.doc_ids_hash`를 무효화 후
   `compute_narrative(topic)` 강제 재생성 (Phase 1 때 AI로 검증한 방식).
3. **Phase 2 착수** (docs/specs/narrative-causal-phase2.md) — 순회(루트·수혜)+`/chain` API → 메르 서사 →
   드리프트 → 머지·교차검증 → 내러티브↔지식 루프. **필수 commit**(D-023). 1단계=순회+/chain부터.

### 새 세션 부트스트랩 (Claude Code에게 첫 지시)
> "docs/HANDOFF.md · SYSTEM.md · DECISIONS.md(D-022~024) · docs/specs/narrative-causal-phase2.md 읽고,
>  §4 체크리스트로 환경 점검한 뒤, crontab 설치 확인 → (필요시 refill) → Phase 2 1단계부터 이어가자."

## 6. 별건 후속 (급하지 않음)
- **런타임 최적화**: ingest enrich가 문서당 `claude -p` CLI 콜드스타트라 느려 한 사이클이 30분 초과.
  배치 enrich나 세션 재사용으로 단축 (락은 겹침만 막지 속도는 그대로).
- **keyword 티어 백필**: enrichments 중 ~1,400건이 keyword 폴백 태깅 상태(LLM 재태깅 대기).
