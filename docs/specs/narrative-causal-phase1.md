# 기획서 — 내러티브 인과 그래프 물질화 (Phase 1)

> 2026-07-17. 상태: **구현 완료** (stakeholder 승인 2026-07-17, 결정 D-023). Phase 2는 후속(필수 commit).
> 비전·결정: docs/specs/narrative-causal-graph.md (§5-0 결정 5개 확정) · 현행 내러티브: pipeline/narrative.py
> 엣지 규약: D-005 · 온톨로지 reserved vocab: D-004 · 시간 정박: D-021 · 5-state: docs/policies/ui-states.md
> 착수 승인 시 DECISIONS.md에 항목 추가.

---

## 1. 목표 (Phase 1의 범위)

내러티브가 매번 만들어 md 텍스트에만 버리던 **인과 구조를 그래프로 물질화**한다. Phase 1은 *토대*만 — 순회 UI·메르 서사·머지·지식 루프는 Phase 2+.

Phase 1 = ① 내러티브 1급 객체화(버전 보존) ② 인과 노드 타입 활성화(macro·policy·event) ③ 내러티브 생성 시 인과 엣지(CAUSES·BENEFITS_FROM, 시간 스탬프) 추출·적재 ④ 카테고리(도메인 렌즈) ⑤ 기존 내러티브 페이지가 새 구조 위에서 그대로 동작 + 인과 체인을 구조화 뷰로 노출(최소).

**비목표(Phase 2+)**: 앞/뒤 끝 순회 UI, 메르식 서사 재작성, 내러티브 머지·교차검증, 내러티브↔지식 루프, 종목까지 하강, 루트 원인 클러스터.

## 2. 데이터 모델

### 2-1. `narratives` (신규 — 1급 객체, 버전 보존)
```sql
narratives (
  id INTEGER PK,
  topic TEXT NOT NULL,            -- theme/sector 이름 (생성 앵커)
  version INTEGER NOT NULL,       -- topic별 1,2,3…
  title TEXT,                     -- 질문형 제목
  body TEXT,                      -- md 본문 (기존 포맷 유지)
  category TEXT,                  -- 도메인 렌즈 (macro|geopolitics|industry|flow|tech|policy) — 복수는 CSV
  doc_ids_hash TEXT,              -- 재생성 가드 (기존 로직 이관)
  model TEXT,
  created_at TEXT,
  superseded_at TEXT              -- 새 버전 나오면 이전 버전 닫음 (삭제 없음)
)
-- UNIQUE(topic, version). 최신 = superseded_at IS NULL.
```
- 기존 `source_digests`(kind='narrative') 7건 → version=1로 이관 후 그 경로 폐기.
- 재생성: 문서 집합 변경(doc_ids_hash) 시 새 version 생성, 이전은 superseded_at 닫음 → **드리프트 추적 가능**.

### 2-2. 노드 — 예약 타입 활성화 (`entities`)
- `entities.type`에 **macro·policy·event** 추가 (D-004 reserved 채움). company·sector·theme·person과 동거, 스키마 무변경(type는 자유 텍스트).
- 정규화: 추출된 노드명 → 기존 엔티티 매칭(정식명 substring + 임베딩 유사도 RELAY_SIM급). 매칭 실패 시에만 신규 생성. 파편화 방어 = 승격/릴레이 접기와 동일 도구 재사용.

### 2-3. 인과 엣지 — `entity_relations` 확장 (D-005 규약 위에)
기존 컬럼(src_id·dst_id·rel_type·epistemic_type·confidence·valid_from/to·source_doc_id)에 ALTER 추가:
```sql
ALTER TABLE entity_relations ADD COLUMN mechanism TEXT;         -- "호르무즈 봉쇄로 공급 차질" (엣지 서사)
ALTER TABLE entity_relations ADD COLUMN reference_period TEXT;  -- 이 인과가 작동하는 시점 (D-021, 수집일 아님)
ALTER TABLE entity_relations ADD COLUMN time_orientation TEXT;  -- past|current|forward (시간 그래디언트)
ALTER TABLE entity_relations ADD COLUMN narrative_id INTEGER;   -- 어느 내러티브(버전)에서 나왔나
```
- `rel_type` ∈ 신규 **`CAUSES`**(원인→결과), **`BENEFITS_FROM`**(수혜주체→동인). 전부 `epistemic_type='hypothesis'`(내러티브 산출 = 가설), confidence·source_doc_id 필수.
- **DAG 유지**: 방향은 원인→결과. 반사성은 reference_period가 다른 두 엣지로(같은 노드의 다른 시점) — 사이클 금지(적재 시 동일 (src,dst,rel_type,reference_period) 재적재는 confidence 강화로 접음).
- **시간 정합성 플래그**: 원인 엣지의 reference_period가 결과보다 뒤면 low-confidence 경고(유사인과 방어).

## 3. 파이프라인 (pipeline/narrative.py 확장)

생성 프롬프트가 md 본문 **더하기** 구조화 인과 JSON을 함께 산출:
```
{ "title","narrative"(md, 기존),
  "category": ["geopolitics","industry"],          -- 도메인 렌즈 (닫힌 어휘)
  "nodes": [{"name","type":"macro|policy|event|company|sector|theme","layer":"event…regime"}],
  "edges": [{"from","to","rel":"CAUSES|BENEFITS_FROM","mechanism",
             "orientation":"past|current|forward","reference_period","confidence"}] }
```
- 모델 opus 유지(이미 그럼). knowledge_block 지식 주입도 유지.
- 적재 순서: narratives INSERT(새 version) → 노드 정규화/생성 → 엣지 적재(narrative_id 연결) → 이전 version superseded.
- **앞의 끝/뒤의 끝은 그래프가 지원**(CAUSES 상류 순회 → regime/structure 루트, BENEFITS_FROM → sector 종착). Phase 1은 적재까지, 순회 *뷰*는 Phase 2. 단 뒤의 끝은 **섹터에서 종착**(종목 노드 생성 안 함).

## 4. API (routers/spine_narrative.py 확장)
- `GET /api/spine/narrative?topic=` — narratives 최신 version에서 조회(source_digests 대체). 응답에 category·version·created_at.
- `GET /api/spine/narrative/{id}/causal` (신규) — 그 내러티브의 인과 서브그래프(nodes·edges) 반환. Phase 1 최소 뷰용.
- `GET /api/spine/narrative/versions?topic=` (신규) — 버전 목록(드리프트 추적 기초). Phase 1은 목록만, 시각화는 P2.
- `/list`·`/compute` 기존 유지(내부만 narratives 사용).

## 5. 화면 (Phase 1 최소)
기존 `/narrative?topic=` 페이지 유지 + 본문 아래 **인과 체인 구조 뷰** 추가:
- 인과 노드·엣지를 순서(시간순)대로 나열 — `[정책] 미-이란 재편 →(공급차질) [event] 호르무즈 봉쇄 →(유가↑) [macro] 유가 → … → [sector] 정유(수혜)`.
- 각 노드 타입 배지, 엣지에 mechanism·시간 방향(회고/현재/전망) 태그.
- category 배지 + version 표기.
- 순회 UI(루트까지 접기/펼치기, 메르 서사)는 Phase 2.

### 5-state
| 상태 | 처리 |
|---|---|
| Empty | 인과 엣지 미추출(구버전 내러티브): 본문만, 구조 뷰 자리에 "인과 구조 미추출 — 재생성 시 생성" |
| Loading | 본문/구조 뷰 각각 스켈레톤 |
| Partial | 본문(캐시) 먼저, 구조 뷰(그래프 조회) 뒤따름 |
| Error | 구조 뷰 조회 실패해도 본문은 노출(구조 뷰만 ErrorState) |
| Ideal | 질문형 제목 → 3줄요약 → 인과 체인 구조 뷰(시간순) → 시나리오 → category·version |

## 6. 마이그레이션
- `narratives` 테이블 생성(init_db) + entity_relations 4컬럼 ALTER.
- 기존 source_digests 7건 → narratives version=1 이관(1회성 스크립트). 인과 엣지는 없음(구버전) — 재생성 시 채워짐.
- cron `compute_narratives`는 그대로(내부가 narratives에 씀).

## 7. 구현 순서
1. DB(narratives + entity_relations ALTER) → 2. narrative.py 생성/적재 로직(JSON 추출·노드 정규화·엣지 적재·버전) → 3. API(topic·causal·versions) → 4. 이관 스크립트 → 5. 프론트 구조 뷰 → 6. 검증(tsc·API·5-state) → SYSTEM.md·DECISIONS.md 갱신.

## 8. Out of Scope (Phase 2+)
앞/뒤 끝 순회 UI·메르 서사·버전 드리프트 시각화·내러티브 머지/교차검증·내러티브↔지식 루프·종목 하강·루트 원인 클러스터.
