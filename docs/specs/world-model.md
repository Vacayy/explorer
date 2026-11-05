# 월드모델 — 지금 · 그래프 · 내 판단

- 상태: P7 구현 계약 (2026-10-16). 셸 [app-shell](app-shell.md) §2의 월드모델 L2를 채운다. 위젯은 [home-widgets](home-widgets.md) §2 계약을 따른다.
- 대체: 옛 월드모델 L2(내러티브·전망·지식 시간축 분할)의 화면 배치. [knowledge-page](knowledge-page.md)의 승격 대기 큐 배치(§4)와 [narrative-causal-phase2](narrative-causal-phase2.md)의 랜딩 블록 순서는 이 문서가 대체한다. 서사 생성·인과 그래프·지식 승격의 동작 자체는 바꾸지 않는다.
- 범위 밖: URL 이전(`/world/*`)과 리다이렉트, 휴면 기능(메르 서사·파급 시나리오 등) 제거, 세계관 브리핑과 메가 서사의 생성 통합.

## 1. 구조

| L2 | 기본 URL | 보기 전환 | 이 탭으로 판정하는 경로 |
|---|---|---|---|
| 지금 | `/narrative` | — (상세는 `?topic=`, 이력은 `/narrative/history`) — 상세·이력도 하위 메뉴가 보인다(2026-11-05 개편 4g) | `/narrative`, `/narrative/history` |
| 그래프 | `/knowledge/ontology` | 온톨로지만(2026-11-05 개편 4g — 옛 변화·검증 지식 `/knowledge`는 `/knowledge/ontology`로 리다이렉트, 쿼리 유지) | `/knowledge` |
| 내 판단 | `/questions` | 질문 · 논지 감사(`/thesis`) · 리포트(`/report`) · 지표 보드(`/questions?view=proxies`) — `thesis/JudgmentFrame`(2026-11-05 개편 4f) | `/questions`, `/question/`, `/thesis`, `/report`, `/proxy-boards`(리다이렉트) |

## 2. 지금 (`/narrative`)

위에서 아래로:

**2026-11-05 개편 4g (ia-redesign §4.25 중 LLM 없는 부분)**:

1. **이번 주 큰 그림** (`world/BigPictureCard`) — 머리: 기준 시각(근거 중 가장 늦은 시각 `inputs_as_of`, KST) · 근거 범위(내러티브 n편 · Market Today n회차 · Overnight n일, 0이어도 그대로) · '어떻게 만드나요?' ⓘ · 'AI 종합 · 검증 필요' · '다시 만들기'(쿨다운·한도면 비활성 + 이유 툴팁). 본문: 주간 생성 줄기 카드 격자(최대 4개 — 서사 2편 이상 또는 Market Today·Overnight 근거 1개 이상인 줄기만, D-315 · 번호 · 합니다체 제목 · 상태 배지 강해짐·엇갈림·약해짐·새로 · 서사 칩 `주제 v버전 · 날짜`, 새 서사엔 '새' · 'Market Today 화두 n · n회차'와 '다음 갱신 앞당김' · 근거 줄 1~3개 = 출처·회차/날짜 + 원문 한 줄). 기준 시각 7일 넘으면 머리 아래 경고 띠('n일 지났어요 · 그 사이 새 버전 n편' + 다시 만들기), 14일 넘으면 흐리게 + '오래됨'. 첫 생성 전에는 엮인 서사(메가)를 줄기 자리에 그린다. 7일 안 새 버전이 없고 생성분도 없으면 "이번 주엔 새로 바뀐 서사가 없어요". **GET은 생성하지 않는다** — 생성은 `pipeline/weekly_big_picture`(주 1회 + 마감 정리 뒤 조건 + 다시 만들기, 셋 합쳐 주 7회 한도).
2. **자리 잡은 전제 · 흔들린 전제** (`world/BigPictureCard` `PremisesCard`, `#premises`) — 저장된 세계관 브리핑의 '자리 잡은 전제'·'도전받는 것' 절을 서버가 문장 그대로 나눈 목록(`premises`, 새로 쓰지 않음). 브리핑이 7일 넘으면 경고 띠('n일 지났어요 · 그 사이 새 내러티브 버전 n편' + '다시 만들기' = 기존 `POST /knowledge/worldview/compute`, 누를 때만), 14일 넘으면 흐리게 + '오래됨'. 아래 접힘 칸: 브리핑 전문 · 검증 지식에서 충돌 중인 전제(`world/contested`, 옛 그래프 › 검증 지식의 '흔들리는 전제').
3. **[내러티브] 이번주 업데이트** (`world/NarrativeChanges`) — 최근 7일 새 버전이 나온 주제(주제별 최신본). 제목 · 주제 · `v버전 · 날짜` | `고리 +n / −m` · '바뀐 것 · ' 한 줄(저장된 `change_summary`, 없으면 `drift_summary`) · 추가(+)·삭제(−) 고리 칩(모바일은 숨김 — 상세에서 본다). 첫 버전이면 "새로 생긴 서사입니다". 처음엔 5편, 나머지는 펼친다.
4. **서사 목록** (`explore/NarrativeList`) — 렌즈 칩 · 정렬 칩(변화순·최신순·비중순·급등순) · 30일 넘게 갱신되지 않은 서사는 기본으로 숨기고 `?old=1`(스위치)로 보인다.

전제 칸: 생성분이 있으면 그 전제(흔들린 전제엔 '이번 주 흔들림' 배지 + 출처 서사 `주제 v버전(날짜) "인용"`), 첫 생성 전에는 세계관 브리핑 절 문장. '만들기'·'다시 만들기'는 모두 큰 그림 생성이다.

### 서사 상세 (`/narrative?topic=`) — 체크포인트

**2026-11-05 개편 4g (§4.18) 배치**: 넓은 화면 2단. 왼쪽 = '‹ 지금 · 서사 목록' → 머리(주제 · AI 생성 · 버전 · 생성 시각 · 비중(Δ%p) · 급등 · 렌즈) · 제목 · 저장/이 내러티브로 대화/갱신 → 3줄 요약 상자(본문의 '3줄 요약' 절을 떼어 번호 목록, `lib/bigPicture.splitSummary`) → 특집 기사 본문 → 체크포인트 → 접힘 칸 '근거'(딛고 선 지식·인과 구조·인과 경로)·'추가 탐구'(메르 모드·파급 시나리오·언급 상위 종목), 펼침은 옛 탭 주소 `?detail_tab=evidence|explore`. 오른쪽 = 이번 버전에서 바뀐 것(`/{id}/diff?summarize=false` — 저장된 드리프트 요약 + 추가·삭제 노드, 새로 요약하지 않음) · 인과 고리(6개, 신뢰·메커니즘) · 버전 이력(최근 6, 누르면 이력 화면) · 관련 서사 · 관련 질문·관련 리포트(접힘). 장중 화두 타임라인(§9)은 5단계.

체크포인트는 본문 아래 `world/NarrativeCheckpoint` 카드:

| 줄 | 원천 | 링크 |
|---|---|---|
| 핵심질문 | 최신 버전의 `core_question`(없으면 가장 최근 값) | 이 주제의 어느 버전에서든 도출된 추적 중 질문이 있으면 `/question/:id` + 확정·선행 판정 배지. 없으면 '질문 제안 대기' 또는 '추적 안 함' |
| 흔들릴 조건 | 이 서사의 승격 지식에 걸린 미발화 반증 조건 + 추적 질문의 하위 질문 반증 조건 (중복 제거, 최대 6) | — |
| 수혜 섹터·종목 | 근본 원인→수혜 경로의 종착 섹터·경로 위 기업 + 서사가 주장한 수혜(BENEFITS_FROM) 쪽 노드 (최대 10) | 기업 → 도시에, 저장된 서사가 있는 주제 → 그 서사, 나머지는 텍스트 |
| 내 종목 | 아래 §5 '내 종목' 조인을 이 주제로 거른 것 | 도시에 |

'종목 발견에서 보기' 버튼: 수혜 후보로 자연어 조건 초안을 만들어 `/discover?intent=natural&q=…`로 연다. 종목 발견은 입력창에 채우기만 하고 실행은 사용자가 누른다. 수혜 후보가 없으면 버튼을 끈다. 읽을 줄이 하나도 없으면 카드를 숨기고, 조회 오류여도 본문은 그대로 보인다.

옆 칸 '관련 질문'의 각 질문은 `/question/:id`로 간다.

## 3. 그래프

- **온톨로지** (`/knowledge/ontology`, `explore/WorldviewPage`) — 기존. 노드 패널의 '등장하는 내러티브' 링크는 SPA 이동(`Link`). 그래프 아래 **인과 그래프 업데이트**(`explore/GraphActivitySection`, `GET /api/spine/causal/activity?days=7&limit=10`, 2026-11-05 D-308로 되살림): 최근 7일 새로 생기거나 연결이 늘어난 노드 · 유형 · 신규/갱신 +n · 수혜 후보 top3. 서사가 있는 주제는 서사로, 없으면 `?focus=`. 수혜 후보 계산이 무거워(단독 약 16초) 접어 두고 펼칠 때만 부른다(타임아웃 90초).
- ~~변화·검증 지식~~ (`/knowledge`) — 2026-11-05 개편 4g에서 화면 제거(ia-redesign §8.6·§10.6). `/knowledge` → `/knowledge/ontology`(쿼리 유지). 세계관 브리핑과 충돌 중인 전제는 지금 › 전제 칸으로, 지식 주입은 ⌘K, 승인은 상단 인박스. 구조 지도·현황 스트립·검증 지식 목록 화면은 없앴다(인과 그래프 업데이트는 D-308로 그래프 아래에 되살림)(지식 API `/api/spine/knowledge/*`는 그대로).

## 4. 내 판단 (`/questions`)

- 질문이 1급 객체다. 보유 논지(`created_by=portfolio`)·관심 이유(`watch`)·논지 감사 승격(`thesis`)·서사 도출(`system`)·언급(`digest`)·직접 입력(`user`)이 모두 같은 질문 행이고 출처를 배지로 구분한다(`QUESTION_ORIGIN`). 종목에 걸린 질문은 종목 코드 칩 → 도시에.
- 논지 감사·리포트·지표 보드는 같은 탭의 보기 전환이다. 공통 틀 `thesis/JudgmentFrame` = 제목 '내 판단' + Tabs `질문 · 논지 감사 · 리포트 · 지표 보드`(주소가 보기를 정한다, `lib/judgment`). 판정 엔진 상태 표시는 범위 밖.
- **지표 보드**(`/questions?view=proxies&board=`, 2026-11-05 개편 4f): 프록시 보드(D-240, `proxy/ProxyBoardsView`) 아래에 컨콜에서 뽑은 지표(옛 탐색 › 컨콜 '프록시' 보기, `proxy/TranscriptProxies`, 접어 둠). 옛 `/proxy-boards?board=`와 `/follow/transcripts?view=proxies`는 여기로 리다이렉트(쿼리 유지).
- **질문 상세**(`/question/:id`): 머리(질문 · 확정/선행 · 출처 배지 · 괴리 · 추적 시작/판정 갱신 날짜) → 판정 요약 → 넓은 화면 2단: 분할정복 트리(서브질문 · 프록시 · 관측 n건 · 관측 대기 n, 프록시 줄에 전체 관측 수 `obs_count`, 줄을 누르면 상세 대화상자) | 질문 종합(낡았으면 'm/d에 만든 결산입니다. 그 뒤 관측이 갱신됐습니다 · 다시 종합'을 맨 위, '아직 미판정·흔들릴 조건'은 접음) · 파급 시나리오(논리상 수혜·피해 쪽 칩 — 인과 추론이지 판정 아님, 전문은 접음). 블록 단위 실패, 낡아도 자동으로 다시 만들지 않는다.
- **논지 감사**(`/thesis?audit=`): 왼쪽 새 논지 감사(작은 입력) · 감사 기록(지금 보는 감사 표시) | 오른쪽 감사 결과(감사한 논지 원문 접음 → 판정 분포 → 진자 분포 — 값이 없으면 '이 감사엔 값 없음' → 주장 카드 · 추적 시작 · 이 논지 다시 감사). `?audit=` 없으면 가장 최근 기록.
- **리포트**(`/report?topic=`): 목록 | 상세 2단(좁은 화면은 하나씩). 상세 = '통합 리포트 · 주제 · 작성일 · 버전' → '작성 이후' 한 줄(Top-pick 주가·12M 선행 PER, 관측이지 판정 아님) → 차트 → 제목·결론·핵심 질문·투자 포인트 요약 → 산업 분석 이하 접음 → 분석 종목(레이팅 말 '상방 우위(비대칭 큼)·상방 우위·중립·하방 우위'(D-307), 옛 영문 레이팅[Hold 포함]은 보일 때 바꿈) → 구성 내러티브 → 논쟁 → 이전 버전. 생성 프롬프트도 같은 말(`pipeline/report.RATING_*`, 제목은 '~의 비대칭이 크다' 식).
- 프록시 대시보드의 '핵심 질문' 링크는 `/questions`.

## 5. 읽기 전용 API (`routers/spine_world.py`, `pipeline/world_reads.py`)

전부 저장된 행만 읽는다. 서사 생성, 세계관 생성, drift 한 줄 생성(`narrative_diff`의 게으른 요약)을 부르지 않는다. `tests/test_world_reads.py`가 LLM·subprocess 진입점 호출 기록이 비어 있는지 확인한다.

| GET `/api/spine/world/…` | 응답 | 쓰는 곳 |
|---|---|---|
| `big-picture` | `{source: generated\|mega, strands[{title, status, narratives[{narrative_id, topic, version, created_at, is_new}], mt_topics, mt_sessions, boost, evidence[{kind, ref, label, text, date}]}], premises{settled[], contested[]}[{text, shaken_by\|null}], generated_at, week, mega[], worldview\|null, as_of, inputs, inputs_as_of, stale_days, new_versions_since, rebuild{available, reason, retry_at, budget_left}}` · `POST big-picture/rebuild` → `{status: ok\|skipped\|cooldown\|budget\|unavailable\|failed\|empty\|off, …}` | 큰 그림 카드·전제 칸·위젯 |
| `changes?days=7&limit=20` | `{days, items[{topic, narrative_id, version, title, category, created_at, drift_summary, change_summary, versions_in_window, is_first, added_count, removed_count, added_edges[≤5], removed_edges[≤5]}], as_of}` — 고리 비교는 직전 버전과의 결정적 diff. `change_summary`(서사가 어떻게 옮겨 갔나 1~2문장)는 저장분, 없는 옛 버전은 `drift_summary` 첫 문장을 100자 안으로 결정적으로 줄인 값, 첫 버전은 null | 바뀐 서사 카드·위젯 |
| `contested?limit=10` | `{items[{id, statement, pace_layer, contested_at, refute, support, latest_refute{doc_id, title, observed_at}}], as_of}` — 활성·충돌 중 지식만 | 흔들리는 전제 카드·위젯 |
| `my-stocks?per_stock=3` | `{stocks[{stock_code, name, kinds[], narratives[{topic, narrative_id, title, version, created_at, drift_summary, edges, via}], latest_drift, latest_at}], members, covered, as_of}` | 내 종목 위젯 |
| `checkpoint?topic=` | `{status ok\|empty, topic, narrative_id, title, core_question, question, falsifiers[], beneficiaries[], my_stocks[]}` | 서사 상세 체크포인트 |

**내 종목 조인**: 종목 묶음 종목(보유·관심, `stock_groups`) → 회사 엔티티(`entities.aliases = stock_code`) → 그 회사가 한쪽 끝인 `CAUSES`·`BENEFITS_FROM` 엣지 중 `source_status ∈ {verified, document}` → ① 엣지를 만든 서사(`narrative_id`)의 주제(`via=edge`), ② 엣지 건너편 노드 이름이 서사 주제인 경우(`via=neighbor`) → 주제별 최신본. 엣지 수가 많은 서사 먼저, 같으면 최근 갱신 순.

## 6. 홈 섹션 (`widgets/world.tsx`)

| id | 이름 | 원천 | 큰 숫자 · 목록 |
|---|---|---|---|
| world.changes | 이번 주 바뀐 서사 | `changes` | 편수 · 서사 행(제목 2줄 · 주제 배지 · 버전/상대 시각 · `change_summary` 2줄). 고리 칩·'바뀐 것'·고리 개수는 두지 않는다(랜딩 카드 전용) |

머리 기준 시각은 응답 `as_of`의 상대 표기, 최신 버전이 7일보다 오래되면 주의 색. 큰 그림·내 종목을 움직이는 서사·흔들리는 전제 위젯은 홈 고정 탭이 쓰지 않아 2026-11-05 개편 7단계에서 지웠다(큰 그림·전제는 Thesis › 지금 화면, `my-stocks` API는 서버에 남음 — 화면 호출 없음).

## 7. 5-state

| 화면 | Loading | Empty | Error | Partial |
|---|---|---|---|---|
| 큰 그림 | Skeleton 2줄 | 메가·브리핑 둘 다 없음 안내 | 다시 시도 | 메가만 또는 브리핑만 |
| 바뀐 서사 | Skeleton 2줄 | "최근 7일 동안 새 버전이 나온 서사가 없습니다" | 다시 시도 | drift 없는 버전은 고리 칩만 |
| 서사 목록 | (기존) | 30일 안 서사 없음 → 오래된 서사 켜기 안내 | (기존) | — |
| 체크포인트 | Skeleton | 카드 숨김 | 카드 숨김(본문 유지) | 있는 줄만 |
| 흔들리는 전제 | Skeleton | "지금 충돌 중인 전제는 없습니다" | 다시 시도 | 반례 문서 없으면 링크 생략 |
| 인과 그래프 업데이트(그래프 아래, 접힘) | 펼친 뒤 Skeleton | "최근 7일 인과 그래프 업데이트가 없습니다" | 다시 시도(그래프는 그대로) | 수혜 후보 없으면 줄 생략 |

## 8. 알려진 남은 일

- 서사가 아직 없는 주제의 상세에 직접 들어가면 기존 상세가 생성을 자동 요청한다. 이 단계의 링크는 저장된 서사가 있는 주제로만 보내 이 경로를 피한다.
- 서사 상세 '변경 이력'은 기존 `/{id}/diff`를 쓰고, drift 한 줄이 없으면 그 GET이 haiku를 부른다.
- 렌즈·정렬 선택은 아직 화면 상태다(URL 아님).
