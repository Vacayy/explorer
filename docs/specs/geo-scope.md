# geo_scope — 인과 주장에 장소 정박 (A방향: 보편 노드 + 스코프 있는 엣지)

> 2026-07-20. 상태: 확정 — 구현 착수 (D-034).
> 배경: 세계관 뷰에서 "전력요금 인상" 같은 보편 개념 노드가 "언제·어디서?"가 없어 정보 가치가
> 약하다는 지적(대화 2026-07-20). 노드는 보편(재사용·반복 패턴)으로 유지하고, **인과 주장(엣지)에
> 시간+장소를 정박**한다 (시간 reference_period은 이미 있음 — geo를 대칭으로 추가).

## 결정 (A방향)

- 노드 = 시간·장소 없는 보편 개념 (그대로).
- 엣지 = 특정 시점·장소에서 성립하는 인과 주장. `reference_period`(시간)에 **`geo_scope`(장소)를 대칭 추가**.
- geo를 1급 노드(예약 타입 `geo`)로 활성화하지 않는다 — 시간이 노드가 아닌데 geo만 노드면 비대칭.
  geo-as-lens/순회는 필요 확인 후 별도 트랙(온톨로지 geo 타입은 reserved 유지).

## 통제 어휘 (파편화 방지 — D-033 교훈)

프리폼 금지(서울/한국/코리아 파편화). LLM은 다음에서 고른다:
`한국 | 미국 | 중국 | 유럽 | 일본 | 대만 | 글로벌 | 기타` (모르면 null).
- `글로벌` = 특정국 아닌 전세계 공통(예: AI CAPEX 사이클). `기타` = 목록 밖 특정 지역.
- 공용 상수 `GEO_VOCAB`(narrative.py)로 3개 프롬프트가 공유.

## 백엔드

1. **스키마**: `ALTER TABLE entity_relations ADD COLUMN geo_scope TEXT` (database.py 마이그레이션).
2. **적재**: `_persist_causal`(narrative.py) — INSERT에 geo_scope 추가, 기존 엣지 UPDATE는
   `geo_scope=COALESCE(geo_scope, ?)`(mechanism과 동일 패턴, 비어있을 때만 채움).
3. **추출 프롬프트 3곳**: narrative.py·doc_causal.py·scenario.py — 엣지 JSON 스키마에 `geo` 추가 +
   "geo ∈ GEO_VOCAB, 모르면 null" 지시.
4. **API**: full_causal_graph(narrative_graph.py)·causal_subgraph(narrative.py) 엣지 SELECT에
   `er.geo_scope` 추가, 출력 dict에 `geo_scope` 포함. spine_causal Worldview.edges는 dict passthrough.
5. **backfill**: `scripts/backfill_geo_scope.py` — geo_scope IS NULL인 엣지의 (from,to,mechanism)에서
   haiku 배치로 GEO_VOCAB 중 추론. dry-run(계획 저장) → 검토 → --apply (consolidate_vocab 패턴 재사용).
   판정 애매하면 null 유지(억지 지정 금지 = 거짓 정밀 방지).

## 프론트

- `WEdge`(types.ts·WorldviewPage)에 `geo_scope?: string | null`.
- 노드 상세(EdgeContextRow): 각 인과 행에 geo 배지(reference_period 옆). + 노드 헤더에 관측 시점 범위
  (그 노드 엣지들의 reference_period min~max).
- EdgeDetailSheet: geo 표시.

## 검증

- BE: `python -c "from main import app"` · init_db로 컬럼 생성.
- FE: tsc --noEmit.
- backfill: dry-run 표본 출력 검토 → 실DB 복사본에서 apply 정합성 확인 후 실적용.

## Out of Scope

- geo 1급 노드/OCCURS_IN 관계 (필요 시 별도).
- 노드 자체의 geo(기업 국적 등 엔티티 메타) — 인과 주장 스코프와 별개.
