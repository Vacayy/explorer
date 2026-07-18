# 기획서 — 세계관 뷰 (인과 그래프 노드-링크 시각화)

> 2026-07-18. 상태: **기획 초안 — stakeholder 리뷰 대기.**
> 배경: narrative-causal-phase2.md §6에서 "노드-링크 풀 인터랙티브 시각화"를 1차 Out of Scope로
> 미뤘으나(당시엔 계층 목록/최소 뷰만), 2026-07-18 논의에서 이 트랙을 먼저 진행하기로 결정.
> Phase 2(순회·메르 서사·드리프트·머지·지식 루프)는 구현 완료 — 이 문서는 그 위에 시각 레이어를 얹는다.

---

## 1. 왜 지금

현재 인과 그래프(entity_relations의 CAUSES/BENEFITS_FROM)는 narrative.py의 `causal_subgraph()`로
**내러티브 하나 단위**로만 볼 수 있다(NarrativePage의 "인과 구조" 리스트). 하지만 D-023의 관통 프레임
"하나의 인과 그래프, 두 개의 속도"가 실제로 성립하려면 — **개별 내러티브를 넘어 그래프 전체가
하나로 이어져 있음을 눈으로 봐야 한다.** related_narratives()가 이미 "AI·HBM·파운드리가
'AI 데이터센터 투자' 노드로 연결됨"을 텍스트로 찾아내고 있으니, 이걸 실제 그래프로 그리면
"세계관"이 문자 그대로 보인다.

## 2. 데이터 — 이미 있는 것 vs 새로 필요한 것

**이미 있음** (narrative.py, narrative_graph.py 재사용):
- 엣지: `entity_relations`(CAUSES/BENEFITS_FROM) — confidence, mechanism, orientation, reference_period
- 교차검증: `corroborated_by`(narrative_edge_evidence 집계), `contested`(반대 방향 공존)
- 승격 지식: `promoted_knowledge_id`
- 순회: 루트(근본원인)/수혜(섹터) 판정 로직(narrative_graph.py `_walk_upstream`/`_walk_downstream`)

**새로 필요**:
- **전역 그래프 조회** — 지금은 `causal_subgraph(narrative_id)`로 narrative_id 스코프만 가능.
  narrative_id 필터 없이 전체 CAUSES/BENEFITS_FROM 엣지 + 노드를 반환하는 `full_causal_graph()`.
- **연결요소(cluster)** — 그래프를 무향으로 봤을 때 서로 이어진 노드 묶음(같은 "세계관"). union-find로
  계산(LLM 0). 내러티브 머지(§2-4)는 이 연결요소의 부분집합 뷰다.
- **노드별 소속 내러티브** — 클릭 시 "이 노드가 등장하는 내러티브"(related_narratives의 역방향).

## 3. 화면 설계

### 3-1. 위치
`/narrative/worldview` (신규) — 기존 `/narrative?topic=`(개별 내러티브)의 형제. 탐색(`/explore`)의
"주목 주제"·"내러티브" 카드에서 "세계관 전체 보기" 링크로 진입.

### 3-2. 레이아웃
- **좌측 그래프 캔버스** (전체 폭의 ~70%): 노드-링크. 좌→우 레이어 배치(dagre) — 근본 원인이 왼쪽,
  수혜 섹터가 오른쪽. 시간 그래디언트 원칙(narrative-causal-graph.md §2)을 시각 언어로 그대로 반영.
- **우측 디테일 패널** (Sheet, 30%): 노드 또는 엣지 클릭 시 — 노드는 유형·소속 내러티브·인접 엣지,
  엣지는 mechanism·orientation·confidence·corroborated_by·contested·promoted_knowledge_id.
- **상단 필터바**: 도메인 렌즈(macro·geopolitics·industry·flow·tech·policy) 체크박스, 노드 검색.

### 3-3. 시각 언어 (기존 컨벤션 재사용)
- 노드 타입 배지: 기존 `NODE_LABEL`(기업/섹터/테마/인물/매크로/정책/사건) 그대로.
- 엣지: CAUSES=실선, BENEFITS_FROM=점선. contested=적색 강조. corroborated_by≥2=굵게.
  promoted_knowledge_id 있음=작은 지식 아이콘.
- 근본원인 노드(들어오는 CAUSES 없음)=hypothesis 틴트, 수혜 섹터 노드=primary 틴트
  (NarrativePage의 ChainPaths와 동일 색 언어 — docs/DESIGN_SYSTEM.md 일관성).
- 연결요소(cluster)별 은은한 배경 그룹핑(옵션, 후순위).

### 5-state
| 상태 | 처리 |
|---|---|
| Empty | 엣지 0건 — "인과 그래프가 아직 비어 있습니다" |
| Loading | 캔버스 스켈레톤 |
| Partial | 클러스터 계산 실패해도 노드·엣지는 표시(클러스터 색만 생략) |
| Error | 전체 페이지 ErrorState |
| Ideal | 필터·검색·디테일 패널 전부 동작 |

## 4. 기술 선택

- **라이브러리**: 현재 recharts·lightweight-charts만 설치(노드-링크 불가). **React Flow(`@xyflow/react`)**
  추천 — React 네이티브 DX, 줌/팬/미니맵 내장, 커스텀 노드/엣지 컴포넌트 지원. 신규 의존성이라 **착수 전
  승인 필요**(shadcn-first 정책과 무관한 별도 카테고리 — 그래프 시각화 전용 라이브러리).
- **레이아웃 알고리즘**: React Flow는 자동 배치를 안 해준다. **dagre**(방향 그래프 계층 배치, 좌→우)
  페어링 추천 — 시간 그래디언트(원인→결과) 원칙과 자연히 맞음. force-directed(d3-force)는 방향성이
  희석돼 이 프로젝트의 "인과는 시간에 종속된다" 철학과 어긋나 기각.
- **연결요소 계산**: 파이썬 백엔드에서 union-find로 계산해 노드에 `cluster_id`를 실어 보낸다
  (프론트에서 재계산 불필요, LLM 0).

## 5. 백엔드 변경 (개요)

- `pipeline/narrative_graph.py`에 추가: `full_causal_graph(conn, category=None) -> dict` — 전체
  노드·엣지 + cluster_id + 노드별 in/out degree. `nodes_in_narratives(conn, entity_id) -> list` —
  이 노드가 등장하는 내러티브(related_narratives의 노드 단위 버전).
- API: `GET /api/spine/causal/worldview?category=` (신규 라우터 또는 spine_narrative.py에 추가),
  `GET /api/spine/causal/node/{entity_id}` (디테일 패널용).

## 6. 구현 순서

1. 백엔드 `full_causal_graph` + cluster 계산 + API 2개 → curl로 실데이터 검증
2. React Flow 설치 승인 확인 → 최소 캔버스(고정 목업 데이터로 렌더링만) → tsc/build
3. 실 API 연결 + dagre 레이아웃 적용
4. 디테일 패널(Sheet) + 필터바
5. 시각 언어 배지(contested·corroborated·promoted) 입히기
6. 5-state 감사 + `/explore`·`/narrative` 진입 링크 연결
7. **브라우저 실제 확인 필수** — 이전 세션들은 브라우저 구동 도구가 없어 tsc/build만으로 검증했음.
   노드-링크 시각화는 특히 렌더링을 눈으로 봐야 하는 기능이라, 로컬 `npm run dev`로 직접 클릭해보는
   과정이 다른 기능보다 훨씬 중요함.

## 7. Out of Scope (이번 트랙)
- 실시간 협업/멀티 유저 뷰 동기화
- 그래프 편집(수동 노드/엣지 추가) — 읽기 전용 관측 뷰
- 클러스터 자동 라벨링(emergent naming) — 후속
