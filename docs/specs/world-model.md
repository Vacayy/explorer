# 월드모델 — 지금 · 그래프 · 내 판단

- 상태: P7 구현 계약 (2026-10-16). 셸 [app-shell](app-shell.md) §2의 월드모델 L2를 채운다. 위젯은 [home-widgets](home-widgets.md) §2 계약을 따른다.
- 대체: 옛 월드모델 L2(내러티브·전망·지식 시간축 분할)의 화면 배치. [knowledge-page](knowledge-page.md)의 승격 대기 큐 배치(§4)와 [narrative-causal-phase2](narrative-causal-phase2.md)의 랜딩 블록 순서는 이 문서가 대체한다. 서사 생성·인과 그래프·지식 승격의 동작 자체는 바꾸지 않는다.
- 범위 밖: URL 이전(`/world/*`)과 리다이렉트, 프록시 보드, 휴면 기능(메르 서사·파급 시나리오 등) 제거, 세계관 브리핑과 메가 서사의 생성 통합.

## 1. 구조

| L2 | 기본 URL | 보기 전환 | 이 탭으로 판정하는 경로 |
|---|---|---|---|
| 지금 | `/narrative` | — (상세는 `?topic=`) | `/narrative`, `/narrative/history` |
| 그래프 | `/knowledge/ontology` | 온톨로지 · 변화·검증 지식(`/knowledge`) — `KnowledgeSubNav` | `/knowledge` |
| 내 판단 | `/questions` | 질문 · 논지 감사(`/thesis`) · 리포트(`/report`) — `OutlookSubNav` | `/questions`, `/question/`, `/thesis`, `/report` |

## 2. 지금 (`/narrative`)

위에서 아래로:

1. **이번 주 큰 그림** (`world/BigPictureCard`) — 살아 있는 엮인 서사(메가)마다 제목 · 관통하는 주제 칩 · 펼치면 본문. 아래에 저장된 세계관 브리핑(접힘, 저장 시각). 저장 이후 입력이 바뀌었으면 주의 색 한 줄 + 그래프 › 변화·검증 지식 링크. **이 카드는 생성하지 않는다.**
2. **이번 주 바뀐 서사** (`world/NarrativeChanges`) — 최근 7일 새 버전이 나온 주제(주제별 최신본). 제목 · 주제 · 버전 · 상대 시각 · 바뀐 것 한 줄(저장된 `drift_summary`) · 새로 생긴 고리(+)·사라진 고리(−) 칩과 개수. 첫 버전이면 "새로 생긴 서사". 처음엔 5편, 나머지는 펼친다.
3. **서사 목록** (`explore/NarrativeList`) — 기존 렌즈·정렬. 30일 넘게 갱신되지 않은 서사는 기본으로 숨기고 `?old=1`(스위치)로 보인다. 보일 때는 흐리게.

### 서사 상세 (`/narrative?topic=`) — 체크포인트

'현재 해석' 탭 맨 위에 `world/NarrativeCheckpoint` 카드:

| 줄 | 원천 | 링크 |
|---|---|---|
| 핵심질문 | 최신 버전의 `core_question`(없으면 가장 최근 값) | 이 주제의 어느 버전에서든 도출된 추적 중 질문이 있으면 `/question/:id` + 확정·선행 판정 배지. 없으면 '질문 제안 대기' 또는 '추적 안 함' |
| 흔들릴 조건 | 이 서사의 승격 지식에 걸린 미발화 반증 조건 + 추적 질문의 하위 질문 반증 조건 (중복 제거, 최대 6) | — |
| 수혜 섹터·종목 | 근본 원인→수혜 경로의 종착 섹터·경로 위 기업 + 서사가 주장한 수혜(BENEFITS_FROM) 쪽 노드 (최대 10) | 기업 → 도시에, 저장된 서사가 있는 주제 → 그 서사, 나머지는 텍스트 |
| 내 종목 | 아래 §5 '내 종목' 조인을 이 주제로 거른 것 | 도시에 |

'종목 발견에서 보기' 버튼: 수혜 후보로 자연어 조건 초안을 만들어 `/discover?intent=natural&q=…`로 연다. 종목 발견은 입력창에 채우기만 하고 실행은 사용자가 누른다. 수혜 후보가 없으면 버튼을 끈다. 읽을 줄이 하나도 없으면 카드를 숨기고, 조회 오류여도 본문은 그대로 보인다.

옆 칸 '관련 질문'의 각 질문은 `/question/:id`로 간다.

## 3. 그래프

- **온톨로지** (`/knowledge/ontology`, `explore/WorldviewPage`) — 기존. 노드 패널의 '등장하는 내러티브' 링크는 SPA 이동(`Link`).
- **변화·검증 지식** (`/knowledge`, `knowledge/KnowledgePage`) — 구조 지도 · 현황 스트립 · **인과 그래프 업데이트**(최근 7일, `explore/GraphActivitySection`) · **흔들리는 전제**(`world/ContestedPremises`) · 주입 콘솔 · 세계관 브리핑(기존 카드, 갱신 경로는 그대로) · 검증 지식 목록.
- 인과 그래프 업데이트의 노드 링크: 저장된 서사가 있는 주제면 그 서사, 아니면(매크로·정책·사건 노드, 서사 없는 테마) `/knowledge/ontology?focus=<id>`.
- 승인 대기(지식 승격 후보)는 이 화면에 두지 않는다. 상단 승인 인박스가 같은 항목을 처리한다. 현황 스트립의 '승격 대기' 개수는 남긴다.

## 4. 내 판단 (`/questions`)

- 질문이 1급 객체다. 보유 논지(`created_by=portfolio`)·관심 이유(`watch`)·논지 감사 승격(`thesis`)·서사 도출(`system`)·언급(`digest`)·직접 입력(`user`)이 모두 같은 질문 행이고 출처를 배지로 구분한다(`QUESTION_ORIGIN`). 종목에 걸린 질문은 종목 코드 칩 → 도시에.
- 논지 감사·리포트는 같은 탭의 보기 전환으로 남긴다. 판정 엔진 상태 표시와 프록시 보드는 이 단계 범위 밖.
- 프록시 대시보드의 '핵심 질문' 링크는 `/questions`.

## 5. 읽기 전용 API (`routers/spine_world.py`, `pipeline/world_reads.py`)

전부 저장된 행만 읽는다. 서사 생성, 세계관 생성, drift 한 줄 생성(`narrative_diff`의 게으른 요약)을 부르지 않는다. `tests/test_world_reads.py`가 LLM·subprocess 진입점 호출 기록이 비어 있는지 확인한다.

| GET `/api/spine/world/…` | 응답 | 쓰는 곳 |
|---|---|---|
| `big-picture` | `{mega[], worldview{briefing, created_at, stale}\|null, as_of}` | 큰 그림 카드·위젯 |
| `changes?days=7&limit=20` | `{days, items[{topic, narrative_id, version, title, category, created_at, drift_summary, versions_in_window, is_first, added_count, removed_count, added_edges[≤5], removed_edges[≤5]}], as_of}` — 고리 비교는 직전 버전과의 결정적 diff | 바뀐 서사 카드·위젯 |
| `contested?limit=10` | `{items[{id, statement, pace_layer, contested_at, refute, support, latest_refute{doc_id, title, observed_at}}], as_of}` — 활성·충돌 중 지식만 | 흔들리는 전제 카드·위젯 |
| `my-stocks?per_stock=3` | `{stocks[{stock_code, name, kinds[], narratives[{topic, narrative_id, title, version, created_at, drift_summary, edges, via}], latest_drift, latest_at}], members, covered, as_of}` | 내 종목 위젯 |
| `checkpoint?topic=` | `{status ok\|empty, topic, narrative_id, title, core_question, question, falsifiers[], beneficiaries[], my_stocks[]}` | 서사 상세 체크포인트 |

**내 종목 조인**: 종목 묶음 종목(보유·관심, `stock_groups`) → 회사 엔티티(`entities.aliases = stock_code`) → 그 회사가 한쪽 끝인 `CAUSES`·`BENEFITS_FROM` 엣지 중 `source_status ∈ {verified, document}` → ① 엣지를 만든 서사(`narrative_id`)의 주제(`via=edge`), ② 엣지 건너편 노드 이름이 서사 주제인 경우(`via=neighbor`) → 주제별 최신본. 엣지 수가 많은 서사 먼저, 같으면 최근 갱신 순.

## 6. 위젯 (`widgets/world.tsx`, 섹션 world)

| id | 이름 | 묶음 | 기본 크기 | 원천 | 큰 숫자 · 목록 |
|---|---|---|---|---|---|
| world.changes | 이번 주 바뀐 서사 | 지금 | 6×4 | `changes` | 편수 · 서사 행(h≥5면 고리 칩) |
| world.big | 이번 주 큰 그림 | 지금 | 6×3 | `big-picture` | 메가 제목 · 주제 칩 · (h≥4) 세계관 첫 문장 |
| world.mystocks | 내 종목을 움직이는 서사 | 지금 | 6×4 | `my-stocks` | 걸린 종목/묶음 종목 · 종목별 서사 칩 · (h≥4) 바뀐 것 |
| world.contested | 흔들리는 전제 | 그래프 | 4×3 | `contested` | 건수 · 진술·층·반박/지지·반례 문서 |

머리 기준 시각은 응답 `as_of`의 상대 표기. 바뀐 서사는 최신 버전이 7일보다 오래되면, 큰 그림은 세계관 브리핑 입력이 바뀌었으면 주의 색. h≤2면 큰 숫자와 한 줄만.

## 7. 5-state

| 화면 | Loading | Empty | Error | Partial |
|---|---|---|---|---|
| 큰 그림 | Skeleton 2줄 | 메가·브리핑 둘 다 없음 안내 | 다시 시도 | 메가만 또는 브리핑만 |
| 바뀐 서사 | Skeleton 2줄 | "최근 7일 동안 새 버전이 나온 서사가 없습니다" | 다시 시도 | drift 없는 버전은 고리 칩만 |
| 서사 목록 | (기존) | 30일 안 서사 없음 → 오래된 서사 켜기 안내 | (기존) | — |
| 체크포인트 | Skeleton | 카드 숨김 | 카드 숨김(본문 유지) | 있는 줄만 |
| 흔들리는 전제 | Skeleton | "지금 충돌 중인 전제는 없습니다" | 다시 시도 | 반례 문서 없으면 링크 생략 |
| 인과 그래프 업데이트 | Skeleton | "최근 7일 인과 그래프 업데이트가 없습니다" | 다시 시도 | 수혜 후보 없으면 줄 생략 |

## 8. 알려진 남은 일

- 서사가 아직 없는 주제의 상세에 직접 들어가면 기존 상세가 생성을 자동 요청한다. 이 단계의 링크는 저장된 서사가 있는 주제로만 보내 이 경로를 피한다.
- 서사 상세 '변경 이력'은 기존 `/{id}/diff`를 쓰고, drift 한 줄이 없으면 그 GET이 haiku를 부른다.
- 렌즈·정렬 선택은 아직 화면 상태다(URL 아님).
