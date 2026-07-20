# 어휘 통합 (vocab consolidation) — theme·macro 노드 파편화 치유

> 2026-07-19. 상태: **확정 — 구현 착수** (D-033).
> 배경: 온톨로지 점검 대화(2026-07-19)에서 실측으로 확인된 병목.

## 1. 문제 (실측)

인과 그래프의 추상 노드(theme 745·macro 149)가 표기 변형으로 파편화되어 있다:

```
AI 거품론·고점론 / AI 고점론                    ← 같은 개념, 다른 노드
AI 데이터센터 투자 / AI 데이터센터 투자 확대
AI 밸류에이션 버블 논쟁 / AI 밸류에이션 버블 우려
AI Agent / AI 에이전트 · AI infrastructure / AI 인프라
금리 / 금리 상승 / 연준 금리인상 / 연준 추가 인상 우려 / 미 연준 추가 인상 예상
```

**결과**: 같은 인과 주장이 다른 노드로 갈라져 corroboration 카운트가 쪼개진다.
2026-07-19 기준 인과 엣지 1,283개 중 2+ 내러티브 교차확인 **35개**, 지식 승격(promoted_knowledge_id) **0건**
— Phase 2 §2-5 내러티브↔지식 루프가 어휘 파편화 때문에 한 번도 발화하지 못했다.

**원인**: `_resolve_or_create_node`(pipeline/narrative.py)가 정확한 이름 매칭만 한다.
D-023이 방어책으로 명시한 "임베딩 dedup"은 실제로 구현된 적 없음 (vocab 주입만 존재).

## 2. 설계 — 두 갈래

**쓰기 시 = 결정적 해소 / 배치 = 의미적 치유.** 쓰기 경로에 LLM·임베딩을 넣지 않는다(느리고 비결정적).

### 2-1. `entity_merges` 테이블 (audit + redirect 겸용)

```sql
CREATE TABLE IF NOT EXISTS entity_merges (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    old_name     TEXT NOT NULL,       -- 병합으로 사라진 노드 이름
    type         TEXT NOT NULL,       -- theme | macro (v1 범위)
    survivor_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    rationale    TEXT,                -- LLM 판정 근거
    merged_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(old_name, type)
);
```

- **redirect**: `_resolve_or_create_node`가 이름 매칭 실패 시(및 생성 전) 이 테이블을 조회 —
  병합으로 사라진 이름이 재등장해도 survivor로 해소된다 (재파편화 방지).
- **audit**: 무엇이 언제 왜 병합됐는지 영구 기록. company의 aliases(=종목코드 semantics)를 오염시키지 않음.

### 2-2. 병합 배치 (`pipeline/vocab.py` + `scripts/consolidate_vocab.py`)

1. **후보 생성 (LLM 0)** — theme·macro 노드 이름을 fastembed(기존 다국어 MiniLM 384d, search.py 인프라 재사용)로
   임베딩 → 같은 type 내 코사인 유사도 ≥ threshold(기본 0.90) 쌍.
2. **판정 (sonnet)** — 각 후보 쌍을 `claude -p` 배치(여러 쌍/콜)로 판정: `same | different`.
   근거: D-028과 동일 논리 — 1회성 토대 작업이라 품질이 이후 지능의 상한 → sonnet.
   "금리"vs"금리 상승"(다름 — 수준/방향), "AI 고점론"vs"AI 거품론·고점론"(같음) 같은 미묘한 쌍을 가르는 게 핵심.
3. **적용** — `same`만 병합. survivor = 인과 엣지 참조 수 많은 쪽, 동률이면 낮은 id(오래된 쪽).
   - `entity_relations` src/dst 재배선 — UNIQUE(src,dst,rel_type,valid_from) 충돌 시 두 엣지를 병합
     (confidence는 max, narrative_edge_evidence는 survivor 엣지로 이관·중복 무시, feedback_note/mechanism 등은 non-null 우선)
   - `entity_links`·기타 entities FK 참조 테이블 전수 재배선 (INSERT OR IGNORE 후 잔여 삭제)
   - loser 행 DELETE (재배선 후이므로 CASCADE 잔여 없음) + `entity_merges` 기록
4. **승인 모델** — `--dry-run`(기본)이 병합 예정 목록 전체를 출력 → 사람이 검토 → `--apply`.
   CLI 배치 승인 = D-020 "기계는 제안, 사람은 승인" 유지. ApprovalsCard 확장(쌍별 승인 UI)은 기각 —
   1회성 백필 수십 쌍에 UI 과투자, 이후 증분은 소량이라 동일 스크립트 재실행으로 충분.

### 2-3. 쓰기 시 해소 강화 (`_resolve_or_create_node`)

정확 이름 매칭 실패 시 `entity_merges(old_name, type)` 조회 → 있으면 survivor id 반환.
이름·타입 정규화(공백 정리)는 유지. **임베딩 비교는 쓰기 경로에 넣지 않는다** — 배치가 주기적으로 치유.

## 3. 범위

- **v1 대상 타입: theme·macro만.** company는 정체성 semantics가 다르고(종목코드), 승격 루프를 죽이는 건 추상 노드.
  person·sector·event·policy는 파편화 규모 확인 후 후속.
- cron 미편입 — 수동 실행(검토 후 apply). 증분 파편화가 관측되면 주간 cron(dry-run 리포트만) 검토.
- UI 없음 (백엔드 전용).

## 4. 검증 기준

- `python -c "from main import app"` 통과.
- dry-run 출력이 후보 쌍·판정·survivor를 사람이 검토 가능한 형태로 나열.
- apply 후: FK 잔여 참조 0 (loser id를 참조하는 행 없음), UNIQUE 위반 없음.
- 효과 지표: corroborated_by(2+) 엣지 수 35 → 증가 여부, 이후 주간 promote에서 승격 발화 여부.

## 5. Out of Scope

- company 정체성 해소(무코드 627개) — 별도 트랙.
- 쓰기 시 임베딩/LLM 해소 — 배치로 충분함이 반증되면 재논의.
- observations 채움·falsifier 숫자 정박 — 다음 우선순위(같은 대화에서 2순위로 확정), 별도 스펙.
