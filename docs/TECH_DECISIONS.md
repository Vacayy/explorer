# 구현 구조와 기술 선택

이 문서는 Explorer의 주요 기능이 **어떤 경로로 실행되고, 어디에 저장되며, 왜 그렇게 구현됐는지** 설명합니다.
전체 API·운영 목록은 [SYSTEM.md](SYSTEM.md), 원칙은 PHILOSOPHY.md(비공개 문서), 당시 결정과 측정 기록은 DECISIONS.md(비공개 문서)에 있습니다.

2026-09-12 코드 대조 기준입니다. 아래의 구현 설명과 향후 과제는 구분해서 읽어주세요. 과거 운영 수량이나 응답 시간을 현재 성능으로 사용하지 않습니다.

- [제품과 구현 범위](#starting-point)
- [주요 기능의 실행 흐름](#implementation)
- [사실·해석·시간을 기록하는 방법](#from-epistemology)
- [LLM 호출과 비용](#from-cost)
  - [작업 단위 모델 정책: As-is → 판단 → To-be](#task-model-policy)
- [저장소·검색·운영](#from-local-constraints)
- [조회 성능과 화면 상태](#from-performance)
- [남아 있는 과제](#open-problems)
- [검증과 문서 유지](#appendix)

<a id="starting-point"></a>
## 제품과 구현 범위

원천 보존·정제 연결·활용의 책임과 현재 저장소별 보존 한계는 [데이터 생명주기 계약](specs/data-lifecycle.md)에 정리한다. 이 계약은 현행 구조와 미구현 개선 기준을 분리하며, 기존 도메인 저장소의 통합 이전을 전제하지 않는다.

관심 있는 투자자와 기업의 자료를 모아 읽고, 기대가 어떻게 달라지는지 살피며, 사용자의 질문과 생각을 함께 보존하는 개인 리서치 도구입니다.
자료 수집·정리·검색은 자동화하고 최종 투자 판단은 사용자에게 남깁니다.

현재 구현은 크게 세 부분입니다.

| 부분 | 하는 일 | 경계 |
|---|---|---|
| 시장·피드 | 시장 지표, 브리핑, 구독 소스와 시스템 요약 조회 | 읽기 시 저장 결과를 활용하며 모든 지표가 실시간인 것은 아님 |
| 스터디·대화 | 문서 보존, 주석, 자료 묶음, 관련 자료 탐색과 설명 | 사용자 선택과 실제 사용한 근거를 기록 |
| 그래프·기대 관측 | 인과 주장과 근거 연결, 메모리반도체 자료 검토 | 기대·가격·수급을 자동으로 연결하는 전체 설계는 미완성 |

로컬 실행과 단일 사용자에 맞춰 운영을 단순하게 유지합니다. LLM 구독료·API 사용량, 실행 지연과 관리 비용은 별도로 발생합니다.

<a id="implementation"></a>
## 주요 기능의 실행 흐름

### 1. 수집한 자료가 피드에 나오기까지

[ingest.py](../scripts/ingest.py)가 등록된 커넥터를 [runner.py](../backend/pipeline/runner.py)로 실행합니다.
소스별 수집 결과는 `raw_documents`에 저장되고, [enrich.py](../backend/pipeline/enrich.py)가 태그·요약·시간 정보를 `enrichments`에 기록합니다.
검색 색인은 [search.py](../backend/pipeline/search.py)가 담당합니다. 수집과 정리 결과를 보존하므로 화면을 열 때 같은 자료를 다시 가져올 필요가 없습니다.

홈 피드는 별도 게시물 원장을 만들지 않고 기존 데이터에서 읽기용 목록을 구성합니다.

```mermaid
flowchart LR
    A[구독 소스의 저장 문서] --> T[timeline SQL 조회]
    B[기업·인물 요약] --> T
    C[컨콜·수출입 통계] --> T
    T --> F[시간순 피드]
    F --> D[문서 상세]
    D --> S[스터디]
```

[spine_feed.py](../backend/routers/spine_feed.py)의 `/api/spine/feed/timeline`과 `/channels`는 [timeline.py](../backend/pipeline/timeline.py)를 사용합니다.
게시·수집·요약 생성 시각을 구분하고, 시간과 안정 ID로 정렬합니다. 조회 상한 시각 `until`을 유지해 페이지를 넘기는 동안 새 게시물 때문에 순서가 밀리는 일을 줄입니다.
이 조회 자체는 LLM 호출이나 수집을 수행하지 않습니다. 다만 원본 요약 캐시가 수정되면 과거 화면까지 불변으로 유지되는 구조는 아닙니다.

화면은 피드 대메뉴 [FeedPage](../frontend/src/components/feed/FeedPage.tsx)와 리더 [ChannelReader](../frontend/src/components/feed/ChannelReader.tsx)로 구성합니다(2026-11-05 대메뉴로 옮겼고, 2026-11-06 옛 홈 피드의 리더 구성으로 되돌렸습니다).
카드·필터·시각의 상세 계약은 [홈·피드 스펙](specs/home-feed.md)에 있습니다.

### 2. 유튜브 자막과 AI 정리본

[spine_doc.py](../backend/routers/spine_doc.py)의 문서 GET은 저장된 자막·정리본·생성 상태를 반환합니다.
화면은 AI 정리본이 없을 때 별도 POST로 생성을 요청하고 완료 상태를 조회합니다.

[youtube_digest.py](../backend/pipeline/youtube_digest.py)는 `youtube_digest_jobs`에 자막을 보존하고 작업 토큰과 상태를 기록합니다.
큐 등록은 `BEGIN IMMEDIATE`로 경쟁을 줄이고, 진행 중인 동일 문서 요청을 재사용합니다. 실패 후에는 명시적으로 재시도합니다.
이렇게 조회와 생성을 분리해 문서 열람이 긴 LLM 작업을 기다리지 않게 했습니다(D-157).

짧은 검색용 요약, 영상 AI 정리본, 원본 자막은 용도가 다릅니다. 이미 소실된 과거 자막까지 복원하는 기능은 아닙니다.
화면 구현은 [DocumentBody](../frontend/src/components/doc/DocumentBody.tsx)를 참고하세요.

### 3. 스터디 본문과 주석

[study.py](../backend/pipeline/study.py)의 `open_document`는 처음 열었을 때의 본문·제목·URL·hash를 `study_sessions`에 고정합니다.
수집 원문이 나중에 바뀌어도 기존 하이라이트의 위치는 바뀌지 않습니다. 유튜브의 저장 본문이 AI 정리본인 경우에는 그 종류를 표시합니다.

[StudyPage](../frontend/src/components/study/StudyPage.tsx)는 DOM 선택 범위를 Unicode code point 위치로 변환합니다.
서버는 고정 본문의 `body[start:end]`와 선택 문자열 `exact`가 같은지 검사한 뒤 `study_annotations`에 저장합니다.
코멘트 수정은 `revision`으로 충돌을 검사하고 삭제는 `deleted_at`으로 표시합니다. 과거 답변에 사용한 주석 내용은 당시 대화 context에 남습니다.

현재 본문은 문자 위치를 유지하기 위해 보관 텍스트로 렌더합니다. Markdown을 별도 DOM으로 변환하거나 이미지·PDF의 영역을 표시하는 기능은 포함하지 않습니다.

### 4. 여러 자료를 묶는 프로젝트와 통합 노트

[study_projects.py](../backend/pipeline/study_projects.py)가 프로젝트와 자료 소속을 관리합니다.

| 저장 위치 | 역할 |
|---|---|
| `study_projects` | 이름, 자유 메모, revision, 프로젝트 대화 연결 |
| `study_project_members` | 포함 자료와 제거 여부 |
| `study_sessions` | 문서·프로젝트별 고정 본문; `project_id=0`은 단일 스터디 |
| `study_annotations` | 인용 위치, 하이라이트, 코멘트 |
| `study_turns` / `study_project_turns` | 요청 키, 질문, 당시 context, 처리 상태 |

같은 자료라도 프로젝트가 다르면 주석을 별도로 관리합니다. 프로젝트에서 자료를 빼도 본문과 주석을 삭제하지 않아 다시 추가하면 이어서 읽을 수 있습니다.
북마크인 `saved_items`와는 독립이며, 본문 붙여넣기로 만든 자료도 북마크나 수집 원문을 만들지 않습니다.

[ProjectPage](../frontend/src/components/study/ProjectPage.tsx)는 단일 스터디의 읽기·주석 컴포넌트를 재사용합니다.
현재는 문서 탭과 두 자료 비교가 남아 있고, 오른쪽은 **노트 / AI 대화**입니다. 노트에는 전체 포함 자료의 인용 카드와 자유 메모를 모으며 출처 태그로 원문 위치에 이동합니다.
여러 자료를 하나의 세로 스크롤로 이어 읽는 변경은 아직 적용 전입니다. 통합 노트는 화면 통합이며 저장 테이블을 합친 것은 아닙니다(D-158·D-160).

### 5. 선택한 문장과 코멘트로 AI에 질문하기

단일·프로젝트 `/ask`는 주석 ID와 revision을 받습니다. 서버가 소속과 변경 여부를 확인하고 인용문·앞뒤 문맥·저장 코멘트를 다시 구성합니다.
클라이언트가 보낸 임의 본문을 그대로 근거로 채택하지 않습니다.

```mermaid
sequenceDiagram
    participant U as 문서 옆 질문창
    participant S as study / study_projects
    participant C as study_coach
    participant A as chat
    participant DB as SQLite
    U->>S: 질문·자료 선택·주석 ID/revision
    S->>DB: 선택 검증·pending 턴/context 저장
    S-->>U: 접수 상태
    S->>C: 백그라운드 실행
    C->>C: 설명 / 수집 자료 탐색 / 웹 확인 선택
    C->>A: 검증한 선택과 실제 탐색 결과
    A->>A: 답변 생성·인용 검증
    S->>DB: 답변·사용 context·complete/error 저장
    U->>S: API로 상태 조회
    S->>DB: 턴 상태 조회
    S-->>U: 상태 반환
    Note over U,A: 대화 API로 저장된 메시지를 별도 조회
```

주석을 선택하지 않은 자료는 본문 앞 16,000자까지, 선택한 주석은 앞뒤 400자 문맥과 함께 사용합니다.
프로젝트 요청은 최대 10자료·40근거·합계 80,000자로 제한하고 초과하면 선택을 줄이도록 응답합니다.
요청 키로 중복 접수를 막고, 중단된 pending 작업은 일정 시간 뒤 명시적으로 정리합니다. 외부 작업 큐가 아닌 FastAPI 백그라운드 작업이므로 프로세스 재시작 시 자동 재개를 보장하지 않습니다.

[study_coach.py](../backend/pipeline/study_coach.py)는 `auto / off / library / web` 설정에 따라 설명 또는 탐색을 준비합니다.
관련 자료 요청은 기존 문서를 제외한 수집 자료 검색으로 연결합니다. 웹 확인은 Claude Code의 WebSearch/WebFetch 결과만 근거로 채택하며, 검색 발췌와 실제 원문 확인을 구분합니다. API 엔진에서는 이 웹 도구 경로를 지원하지 않습니다.

후속 질문에서는 완료된 턴의 `context_ref`를 사용하고 동일 주석 전문을 다시 첨부하지 않습니다. 새 선택은 별도 snapshot입니다.
이전 대화와 짧은 학습 초점은 남으므로 “맥락을 전혀 보내지 않는다”는 의미는 아닙니다(D-159).
자유 메모는 AI에 자동으로 주입되지 않으며, 주석의 저장 코멘트가 선택 context에 포함됩니다.

### 6. 일반 대화와 공통 처리

[chat.py](../backend/pipeline/chat.py)의 일반 경로는 `route → gather → review → synthesize → verify`입니다.
질문에 맞는 자료를 모으고 부족하면 제한된 추가 탐색 후 답변을 만듭니다. 스터디는 일반 라우터를 우회하고 위의 학습 context와 탐색을 준비한 뒤 같은 합성·인용 검증을 사용합니다.
인용 검증은 답변의 근거 참조를 점검하는 단계이며 모든 문장의 진실성을 보장하지는 않습니다.

대화는 `conversations`·`chat_messages`에 남습니다. [chat_memory.py](../backend/pipeline/chat_memory.py)가 최근 대화와 상태를 불러옵니다.
일반 대화의 `attached_doc_ids`는 사용자가 읽던 자료 선택을 유지하고, 답변 드래그 인용은 선택 문장·문단·근거와 길이 제한이 있는 이전 답변을 함께 전달합니다(D-145·D-146·D-150).

### 7. 인과 그래프와 기대 변화 실험

[doc_causal.py](../backend/pipeline/doc_causal.py)는 문서에서, [narrative.py](../backend/pipeline/narrative.py)는 종합 과정에서 인과 주장을 만듭니다.
[consolidation.py](../backend/pipeline/consolidation.py)의 승격 배치는 근거를 대조하고 `knowledge`의 후보를 만듭니다. 후보 생성·근거 병합과 최종 채택은 다른 동작입니다.
[narrative_graph.py](../backend/pipeline/narrative_graph.py)는 연결을 순회해 화면에서 살펴볼 그래프를 구성합니다.
문서가 같은 주장을 반복한다고 실제 인과관계가 입증되는 것은 아니므로 독립성·반박·관측을 따로 다룹니다.

기대 변화 관측은 [experiment_expectations.py](../backend/routers/experiment_expectations.py)의 별도 라우터로 추가했습니다.
[expectation_store.py](../backend/pipeline/expectation_store.py)는 검토 결과를 운영 DB 옆 `expectations_experiment.sqlite`에 저장합니다.
기존 데이터는 읽기 참조하고 원장 검토가 운영 그래프를 교체하지 않습니다. 메모리 자료를 읽고 첨부해 대화하는 경로와 발언 검토 원장은 구현돼 있습니다.
가격·펀더멘털·심리·수급의 자동 결합은 공통 설계(비공개 문서)에 있는 후속 범위입니다.

<a id="from-epistemology"></a>
## 사실·해석·시간을 기록하는 방법

<a id="epistemic-type"></a>
`entity_relations.epistemic_type`은 사실·관측 해석·가설을 구분합니다. LLM이 만든 인과 주장은 가설로 다루는 것이 원칙입니다.
다만 **모든 산출물에 같은 컬럼이 있거나 출처가 DB 제약으로 필수인 것은 아닙니다.** 실제 스키마에서 `source_doc_id`와 `confidence`는 nullable이며, 스터디·요약은 각자의 본문 종류·모델·context 필드로 출처와 생성 경로를 기록합니다.

<a id="four-axes"></a>
인과 주장에는 `confidence`, `effect_direction`, `effect_strength`, `obs_confirmed_at`을 구분합니다.
“영향이 크다”와 “그 주장이 믿을 만하다”는 다른 정보입니다. 경로 신뢰도는 예상 수익률이나 인과 효과의 크기가 아닙니다.
강도는 `unknown / weak / moderate / strong`처럼 범주로 표현해 근거 없는 소수점 정밀도를 피합니다(D-065·D-066).

<a id="salience-conviction"></a>
지식의 `salience`와 `conviction`도 구분합니다. 언급이 많다는 것은 수집한 자료 안에서의 주목도이며, 투자자 전체의 합의나 사실 여부를 뜻하지 않습니다.
유명한 사람의 단발 발언도 검토할 자료이며 그 자체가 강한 증명은 아닙니다.

<a id="time-anchoring"></a>
태깅은 `time_orientation`과 `reference_period`를 함께 추출합니다. 별도 호출을 줄이지만 출력 토큰까지 무료라는 뜻은 아닙니다.
발행일과 전망 대상 기간을 구분하고, 추출 오류나 기간 미상은 이후 검토에서 확인해야 합니다.

<a id="facts-vs-lenses"></a>
역사적 사건과 해석 프레임도 분리합니다. [lenses.py](../backend/pipeline/lenses.py)는 관점과 질문을 제공하는 역할이며, 렌즈를 적용했다는 이유로 그 설명이 확증된 지식이 되지는 않습니다.

<a id="from-cost"></a>
## LLM 호출과 비용

<a id="subscription-auth"></a>
[enrich.llm_engine](../backend/pipeline/enrich.py)은 `ENRICH_ENGINE=claude-code`이면 Claude CLI 모드를 우선합니다. 실행 파일이 없어도 설정 모드를 유지해 공용 러너의 Codex 대체 경로에 도달합니다(2026-11-11 코드 기준). 그 조건이 아니고 `ANTHROPIC_API_KEY`가 있으면 API를 사용합니다.
따라서 API 키를 추가했다고 항상 API로 전환되지는 않습니다.
[llm.py](../backend/pipeline/llm.py)는 일반 생성의 공통 호출·스트리밍·사용량 기록과 Claude→Codex failover를 제공합니다. 시장 분석과 주간 수동 Codex 재개에는 전용 경로가 남아 있습니다. 작업별 모델 설정은 아직 기능별로 분산돼 있습니다.

기본 CLI 호출은 프로젝트·사용자 설정을 로드하지 않고 도구를 끕니다. 스터디 웹 탐색에만 WebSearch/WebFetch를 명시적으로 열고 턴 수를 제한합니다.
수집 문서나 코멘트 안의 지시를 실행 권한으로 취급하지 않습니다.

<a id="model-tiers"></a>
| 용도 | 현재 코드의 기본값 | 확인 위치 |
|---|---|---|
| 단일 문서 태깅 | haiku | `enrich.py` |
| 태깅 배치 백필 | sonnet | `enrich.py`의 `BATCH_MODEL` |
| 대화 라우팅·추가 탐색 판단 | haiku | `chat.py`의 `CHAT_ROUTER_MODEL` |
| 대화·스터디 답변 합성 | sonnet | `chat.py`의 `RAG_MODEL` |
| 스터디 탐색 계획·웹 읽기 | haiku | `study_coach.py` |
| 내러티브·지식 종합 | opus | `narrative.py`·`consolidation.py` |

모델명은 기본값이며 환경 설정이나 개별 경로에 따라 다릅니다. “빈번한 작업은 무조건 haiku” 같은 전역 규칙으로 해석하지 않습니다.

<a id="hash-gates"></a>
재생성 가능한 요약·종합에는 문서 집합·입력·프롬프트 서명 등을 이용한 캐시 가드를 둡니다. 사용자 질문처럼 매번 의미가 다른 요청은 같은 정책을 적용하지 않습니다.
입력·모델·프롬프트 변경 시 어떤 캐시를 다시 만들지는 각 생성 모듈의 계약입니다.

<a id="measured-changes"></a>
과거 비용 점검으로 내러티브 배치 빈도(D-122), 닫힌 구간 다이제스트(D-124), 영상 선택 생성(D-115·D-157), effort 설정(D-117), 연속 실패 차단(D-119)을 조정했습니다.
당시 수치와 조건은 결정 이력에 보존합니다. 현재 품질·지연·사용량 평가는 실제 작업 로그로 다시 확인해야 합니다.

<a id="code-judges-llm-narrates"></a>
명확한 수치 규칙·중복 판정·예산 제한·정렬은 코드로 처리합니다. 의미 추출·비교·설명에는 LLM을 사용합니다.
LLM도 분류와 판단을 수행하므로 “서술만 LLM이 한다”는 설명은 맞지 않습니다. 의미 판단은 근거와 함께 검토 가능한 결과로 남깁니다.

<a id="approval-gate"></a>
승인 경계는 동작별로 다릅니다. 수집·태깅·예약 요약은 설정된 자동화로, 스터디 저장·질문은 사용자 요청으로 실행합니다.
어휘 병합·리포트 제안 등 승인 큐를 사용하는 경로는 해당 계약에 따라 채택 후 실행합니다. 시스템 전체가 승인 전 무행동인 것은 아닙니다.

<a id="task-model-policy"></a>
### 작업 단위 모델 정책 — As-is → 판단 → To-be (2026-11-11)

**상태: 1차 작업 레지스트리 이관 구현(2026-11-11).** 아래 As-is는 이관 직전 조사 기록이며, To-be의 전체 deadline·논리 호출 추적은 후속 단계다. 사용자 재시작 확인 후 live 계약 검사 198개 통과·실패 0·미검사 8을 확인했다. 조사 기준은 이관 전 작업 트리다. 앞선 Claude→Codex failover 코드와 Sol 설정을 포함한다. live 계약 검사는 HTTP 응답 형식 검증이며 실제 모델 품질 평가와는 구분한다. 구현 계약은 [chat-harness](specs/chat-harness.md#작업-단위-정책-이관-계약)에 둔다.

#### As-is — 실행은 모였지만 정책은 흩어져 있다

현재 흐름은 `기능 → llm.run(model/effort/timeout/tools/job) → Claude → 조건부 Codex`다. [llm.py](../backend/pipeline/llm.py)는 실행·전환·사용량 기록을 공통 처리한다. 대체 모델은 `CODEX_FALLBACK_MODEL` 한 곳에서 바꾸므로 Codex 모델 변경을 위해 모든 호출부를 수정할 필요는 없다.

반면 **어떤 작업에 어떤 정책을 적용하는지**는 호출부에 남아 있다.

| 코드 근거 | 현 상태 | 문제점 |
|---|---|---|
| [chat.py](../backend/pipeline/chat.py), [chat_memory.py](../backend/pipeline/chat_memory.py) | route/review=haiku·low·120초, answer=sonnet·300초, note=haiku·low·120초. 환경변수와 상수가 섞임 | 작업별 모델·지연 정책을 비교하거나 바꾸려면 기능 코드를 읽어야 함 |
| [enrich.py](../backend/pipeline/enrich.py) | 단건 haiku, 배치 sonnet; `_call_claude_code`가 호출 모듈 이름을 job으로 추정 | `enrich` 같은 모듈 단위 이름으로는 태깅·시간 분류·배치를 구별하기 어려움 |
| [narrative.py](../backend/pipeline/narrative.py) | 주 생성 opus, 근거 재확인·변화 요약 haiku | 기능 하나를 모델 하나로 묶으면 다른 난이도의 작업이 잘못 합쳐짐 |
| [llm.run](../backend/pipeline/llm.py) | 설정·입력 검증·provider 분기·failover·원장 기록이 한 함수에 있음 | 별도 `llm.py` 파일이 있다는 것만으로 정책까지 모듈화됐다고 볼 수 없음 |
| [enrich._enrich_llm](../backend/pipeline/enrich.py) | 실제 Codex 응답이어도 저장 label은 요청 시 `claude-code/haiku`; 시도 원장에는 실제 engine/model 기록 | 산출물 모델 표기와 실행 원장이 다를 수 있음. 요청 티어와 실제 모델을 구분해야 함 |
| [youtube.digest_transcript](../backend/pipeline/connectors/youtube.py), [scenario.py](../backend/pipeline/scenario.py), [upside_model.py](../backend/pipeline/upside_model.py) | 호출자 반복과 공용 failover가 공존. 각 provider에 원 timeout을 다시 줌 | 반복 횟수·총 대기시간이 여러 층에서 정해짐. worker의 외부 제한이 먼저 종료시킬 수도 있음 |
| [market_analysis/model.py](../backend/pipeline/market_analysis/model.py), [weekly/worker.py](../backend/pipeline/weekly/worker.py) | 시장 분석은 취소·실측 달러 예산·별도 격리, 주간 리포트는 worker 및 수동 Codex 경로 보유 | 이 경로를 문자열 응답 하나로 평탄화하면 기존 보장이 사라짐 |
| [llm_calls 스키마](../backend/database.py) | job·model·engine·usage·cost·ok·error는 있으나 논리 호출 ID·시도 번호·정책 버전은 없음 | 같은 작업의 Claude 실패와 Codex 성공을 정확히 한 호출로 묶어 비교하기 어려움 |

AST 확인에서 `llm.run` 직접 호출 25곳, `_call_claude_code` 호출 37곳이 44개 파일에 있었다. 이는 이 두 이름만 센 작업 트리 스냅샷이며 import 별칭·전용 어댑터까지 포함한 전체 호출 수가 아니다. 이전에 이관한 직접 CLI 호출도 포함하므로 과거 코드 수량으로 재사용하지 않는다.

#### 판단 — 작업 이름과 provider 선택을 분리한다

외부 자료의 원칙과 이 저장소에 내리는 판단을 구분했다.

| 조사 자료 | 확인한 원칙 | Explorer 적용 판단 |
|---|---|---|
| [Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents) | 단순하고 조합 가능한 구조를 우선하고, 구분 가능한 작업은 경로를 나눌 수 있음 | 호출부가 이미 작업을 알고 있으므로 **명시적인 task ID로 결정적 조회**. 라우팅용 LLM 호출을 추가할 이유가 없음. 이 자료는 2024년 패턴 설명이므로 최신 SDK 사양의 근거로 쓰지 않음 |
| [LiteLLM: Router concepts](https://docs.litellm.ai/docs/router/learn/concepts) | 호출자가 요청하는 논리적 이름과 실제 배포 대상을 분리함 | 작업→정책→provider를 분리하되, 작업은 모델 alias보다 출력·권한 계약까지 포함하는 단위로 둠 |
| [LiteLLM: Reliability](https://docs.litellm.ai/docs/router/learn/reliability) | 오류 종류별 처리, retry/fallback 구분, 재시도 담당 계층을 명시함 | `ValueError` 전체를 공급자 장애로 간주하지 않고 입력·응답 envelope·결과 스키마 오류를 구분. host의 재시도 예산은 공용 runner가 관리 |
| [AWS: Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/) | timeout을 두고, 재시도의 부하·부작용과 계층별 증폭을 고려해야 함 | 논리 호출의 전체 deadline과 각 시도의 상한을 분리. 이미 공개한 텍스트와 도구 실행 후 실패는 무조건 재생하지 않음 |

**채택: Python 타입이 있는 작업 레지스트리 + 기존 공용 runner + provider별 어댑터.** 작업 정책은 frozen dataclass 등으로 표현하고 시작 시 검증한다. 단일 로컬 서비스에서 코드 리뷰·타입 검사·테스트가 가능한 이 방식이 현재 변경 규모에 맞다. 아래 대안 선택은 위 자료와 현재 코드에 근거한 설계 판단이며 성능 벤치마크 결과가 아니다.

| 대안 | 이점 | 이번 판단 |
|---|---|---|
| 공용 runner만 유지하고 기능별 model 인자를 계속 전달 | 수정량 작음 | 작업 정책 분산과 호출자 우회가 그대로 남아 기각 |
| **타입 있는 Python 작업 레지스트리** | 기존 도구로 검증, 프롬프트와 정책 분리, 별도 서비스 불필요 | 채택 |
| YAML/TOML 정책 파일 | 운영자가 코드 없이 편집하기 쉬움 | 현재는 검증·기본값·환경변수 우선순위 계층만 늘어남. 운영 UI/비개발자 편집 요구가 생기면 재검토 |
| LiteLLM gateway 도입 | 그룹·라우팅·실패 처리·로그 기능 제공 | 지금은 기존 CLI 어댑터와 별도 프로세스의 운영 전환까지 포함해 범위가 커짐. **구독 인증을 지원하지 않아서 기각하는 것은 아님**: [현재 구독 연동 문서](https://docs.litellm.ai/docs/subscriptions)는 Claude/Codex와 proxy 전제를 명시함. 로컬 예산·취소·도구 증거 계약의 동등성은 별도 검증 필요 |
| LLM이 매 요청의 모델을 선택 | 입력별 난이도 조절 가능 | 작업이 이미 정해져 있고 추가 지연·평가 부담이 생기므로 기각 |

#### To-be — 호출부는 작업과 입력만 전달한다

```python
# 구현된 작업 인터페이스
result = llm.run(task="chat.answer", prompt=prompt, system=system, on_text=on_text)
result = llm.run(task="document.tag", prompt=prompt)
```

```mermaid
flowchart LR
    A[기능: task + 입력 + 결과 검증] --> B[작업 정책 조회·검증]
    B --> C[공용 실행: deadline·전환·시도 기록]
    C --> D[Claude CLI 어댑터]
    C --> E[Codex CLI 어댑터]
    C --> F[Anthropic API 어댑터]
    D --> G[공통 결과: 실제 engine·model·usage]
    E --> G
    F --> G
```

- **작업의 경계**: `document.tag`, `document.time_classify`, `document.tag_batch`, `chat.route`, `chat.review`, `chat.answer`, `chat.note`, `narrative.generate`, `narrative.diff`, `image.read`, `study.web`. 같은 파일에 있어도 품질·출력·권한·시간 요구가 다르면 분리한다. `haiku_task`나 파일명처럼 구현을 이름에 넣지 않는다.
- **정책 소유권**: primary/fallback의 engine·model·effort, 시도 상한·전체 제한, 도구 허용 범위, 출력 모드·필요 capability, 재시도 가능한 오류를 중앙에서 관리한다. `job`은 task에서 정하고 호출부에서 별도로 다르게 지정하지 않는다. 이미지 경로·schema·stream callback은 실행 입력이며 task가 허용한 범위 안에서만 받는다.
- **프롬프트·결과 소유권**: 프롬프트 작성, 자료 수집, 결과의 업무적 검증·정규화·DB 저장은 기능에 남긴다. 정책 파일에 프롬프트나 업무 SQL을 모으지 않는다. 기존 정규화/허용값 계약도 유지한다.
- **정책 해석**: 코드 기본값→중앙에 명시한 환경변수 override→불변 resolved policy. 로드 시 잘못된 작업·모델·effort·순환 fallback·미지원 capability를 검사한다. 요청 파라미터로 모델·권한을 우회할 수 없게 한다. 기존 환경변수 이름은 중앙 resolver에서 보존하거나 이관표와 함께 제거하며 조용히 무시하지 않는다.
- **provider 차이 보존**: `effort` 문자열을 무조건 복사하지 않고 provider가 지원하는 값인지 검증한다. schema 전달·스트리밍·이미지·웹 근거·정확한 비용 보고는 각각 별도 능력이다. `study.web`은 현재 Claude 도구 증거 계약 때문에 fallback 없음. 시장 분석의 정확한 달러 비용·취소 계약은 전용 경로로 명시하며 일반 runner 도입만으로 완료 처리하지 않는다.
- **실패 정책**: 정상 응답을 모델이 달라졌다는 이유로 재호출하지 않는다. 일시 장애·인증/한도·응답 envelope 오류를 구분하고, 입력 오류·callback 오류·취소는 전환하지 않는다. 업무 JSON/의미 검증 실패는 provider 장애와 별도이며 수정 재생성을 허용할지는 작업별로 정한다. 콘텐츠 정책 거절을 우회하기 위한 전환은 두지 않는다.
- **시간·재시도**: `attempt_timeout`과 논리 호출의 `total_timeout`을 구분하고 monotonic deadline의 남은 시간만 다음 시도에 준다. host 재시도는 runner 한 곳에서 담당하고, CLI 내부 재시도는 통제 가능한 범위와 실제 관측 시도를 구분한다. 이미 발행한 스트림은 이어 붙이지 않는다. 파싱 실패 수정 호출도 전체 예산에 포함한다.
- **관측·표기**: 요청 task·정책 버전과 실제 engine/model을 분리한다. 원장에는 논리 호출 ID·시도 번호·전환 사유·시간/usage를 연결한다. Codex 비용 미제공은 NULL 유지. 산출물에는 실제 결과 메타데이터를 사용하고, 기존 캐시의 모델 티어 의미를 조사한 뒤 정책 변경의 무효화 범위를 정한다. 과거 산출물의 provider를 추정해 다시 쓰지 않는다.

**적용 순서**는 계약 고정 → 작업 레지스트리/설정 중앙화 → 기능 묶음별 이관·옛 우회 제거 → 관측/총 deadline 개선이다. 첫 단계는 기존 모델·effort·각 시도 timeout·도구·결과를 보존한다. 전체 deadline 도입과 정책 튜닝은 별도 동작 변경으로 검증한다. 시장 분석·실험용 수동 provider 선택은 동일한 능력/예산 계약을 검증하기 전까지 명시적인 예외로 남긴다.

**전체 단계 완료 기준**: 일반 기능에서 모델 문자열·CLI 호출·provider 선택·LLM 설정용 `os.getenv`가 사라지고, 등록되지 않은 task는 실행 전에 실패한다. 작업별 설정을 바꾸면 해당 작업만 바뀌어야 한다. 기존 schema·이미지·웹 근거·스트리밍·캐시 동작이 유지되고, 실패 시도와 최종 산출물의 실제 모델을 연결할 수 있어야 한다. 검증은 provider를 호출하지 않는 정책 해석/이관 동등성 테스트를 먼저 수행하고, 소수의 실제 Claude/Codex 호출로 어댑터를 확인한다. 백엔드 재시작 후 live 계약 검증까지 통과해야 운영 적용으로 기록한다.


<a id="from-local-constraints"></a>
## 저장소·검색·운영

<a id="single-sqlite"></a>
운영 데이터는 SQLite에 둡니다. [database.py](../backend/database.py)는 WAL, 외래키 검사, 30초 busy timeout을 설정합니다.
별도 DB 서버를 운영하지 않아도 되지만 동시 쓰기와 장시간 트랜잭션의 제약은 남습니다. 실험 원장은 별도 SQLite 파일이므로 저장소 전체가 파일 하나인 것도 아닙니다.

백업은 실행 중 DB 파일을 단순 복사하지 않습니다. [backup.py](../scripts/backup.py)가 `VACUUM INTO`로 snapshot을 만들고 압축·무결성 검사를 수행하며 vault·media도 보관합니다.
스터디 주석·대화·자유 메모는 운영 DB의 사용자 원본입니다. 기대 실험 DB는 별도 파일이므로 운영 DB 백업만으로 보존됐다고 간주하면 안 됩니다.

<a id="hybrid-search"></a>
검색은 FTS5와 sqlite-vec의 후보를 RRF 순위로 합칩니다. 각 검색 방식의 상위 후보를 보장하는 쿼터도 있어 순수 RRF만 적용한 구현은 아닙니다.
fastembed로 질의를 로컬 임베딩하며, 벡터 확장을 사용할 수 없는 경로는 키워드 검색만 남을 수 있습니다. 첫 임베딩 초기화 비용과 한국어·별칭 검색 품질은 별도 확인 대상입니다.

<a id="launchd-not-cron"></a>
수집·브리핑 배치는 [install_launchd.py](../scripts/install_launchd.py)로 macOS user agent에 등록합니다.
로컬 인증과 스케줄 실행 문제를 겪고 선택한 방식입니다(D-106). 기기 전원이 꺼져 있으면 실행되지 않으며, 누락 회차가 모두 개별 재생되는 것을 보장하지 않습니다.

<a id="process-lock"></a>
[run_chain.sh](../scripts/run_chain.sh)는 디렉터리 락과 PID 확인으로 체인 중복 실행을 줄입니다.
이는 API의 모든 쓰기를 직렬화하는 전역 락이 아닙니다. DB 트랜잭션, 생성 작업별 pending 상태, 수집 체인 락은 서로 다른 충돌을 다룹니다.

<a id="from-performance"></a>
## 조회 성능과 화면 상태

<a id="no-fetch-on-read"></a>
홈 피드와 문서 상세는 저장된 결과를 읽습니다. 지수 GET은 TTL이 만료되면 갱신을 `BackgroundTasks`로 예약하고 저장분을 반환합니다.
이 원칙을 전체 레거시 API가 이미 만족한다고 단정하지 않습니다. [spine_indices.py](../backend/routers/spine_indices.py)의 수동 snapshot POST처럼 외부 수집을 기다리는 경로도 있습니다.

<a id="semantic-invalidation"></a>
지수 API의 갱신 TTL은 하나라도 정규장이 열려 있으면 10분, 모두 닫혔으면 60분입니다. 화면의 조회 간격과 외부 데이터 갱신 TTL은 구분해야 합니다.

<a id="state-from-data"></a>
화면은 수집 시각·관측일과 생성 작업의 상태를 함께 사용합니다. 값이 오래됐다는 표시와 생성 중이라는 표시는 서로 다른 정보입니다.
실패한 자료가 있어도 나머지를 읽을 수 있도록 모듈별 상태를 나눕니다.

[PageLayout](../frontend/src/components/shared/PageLayout.tsx)은 헤더·본문 등 슬롯을 제공하고, [DetailLayout](../frontend/src/components/shared/DetailLayout.tsx)은 상세 읽기 화면의 공통 배치를 담당합니다.
타이포그래피와 색상·간격은 [디자인 시스템](DESIGN_SYSTEM.md)에 정의합니다. IBM 계열 본문 14px을 기준으로 하며 데이터 밀도와 모바일 가독성을 함께 조정합니다.
URL은 자료 ID·필터·복귀 경로에, React 상태와 브라우저 저장소는 팔레트·패널·초안·스크롤 같은 UI 상태에 사용합니다. 모든 탭이 URL 상태인 것은 아닙니다.

<a id="deferred"></a>
<a id="two-worlds"></a>
국내 기업 재무·주가 테이블과 문서·그래프 테이블은 함께 유지합니다. 기대 관측 실험도 기존 시스템을 교체하지 않는 별도 라우터로 추가했습니다.
<a id="no-deploy"></a>
다중 사용자·상시 가용성·다중 워커가 필요해지면 DB뿐 아니라 인증, 작업 큐, 파일 저장소, 복구 방식도 함께 재검토해야 합니다.

<a id="open-problems"></a>
## 남아 있는 과제

<a id="unclosed-loop"></a>
- **인과 검증**: 문서 간 일치와 실제 관측의 확인은 다릅니다. 코드 경로가 존재한다는 것과 운영에서 유효한 검증 사례가 쌓였다는 것도 구분해야 합니다. 과거의 “확인 0건” 수치를 이번 점검에서 다시 측정하지 않았으므로 현재 상태로 반복하지 않습니다.

<a id="other-open"></a>

- **기대 변화**: 발언·기간·대상을 비교하는 실험은 있지만, 기대와 시장 가격·파생상품 수급을 자동으로 연결하는 전체 흐름은 미구현입니다.
- **스터디**: 연속 세로 읽기, 자료 순서 관리, 미수집 URL 자동 가져오기, 이미지/PDF 주석이 남아 있습니다.
- **작업 복구**: 프로세스가 종료되면 진행 중 생성이 중단될 수 있습니다. 상태 표시·중단 정리와 자동 재실행은 다른 기능입니다.
- **자료 규모**: 현재 프로젝트 통합 노트는 포함 문서의 StudyWorkspace를 마운트해 주석을 모읍니다. 대형 프로젝트에는 본문 조회·렌더 비용을 줄이는 분리가 필요할 수 있습니다.
- **품질 평가**: 인용 검증과 단위 테스트만으로 설명의 유용성·검색 누락·인과 해석 품질을 확인할 수는 없습니다. 실제 읽기 사례의 별도 평가가 필요합니다.

<a id="appendix"></a>
## 검증과 문서 유지

| 확인할 계약 | 테스트·문서 |
|---|---|
| 스터디 선택 범위·revision·대화 저장 | `backend/tests/test_study.py` |
| 프로젝트 격리·자료 제거·이관 | `backend/tests/test_study_projects.py` |
| 후속 context·관련 자료·웹 근거 | `backend/tests/test_study_coach.py` |
| 유튜브 자막·생성 상태 | `backend/tests/test_youtube_digest.py` |
| 피드·시장 입력 | `backend/tests/test_timeline.py`, `test_home_market_order.py`, `test_macro_inputs.py` |
| 기대 관측 실험 | `backend/tests/test_expectation_*.py` |
| UI 행동과 미구현 범위 | [기능별 스펙](specs/README.md) |

저장소 루트에서 백엔드 계약 테스트와 프론트엔드 타입 검사·빌드를 실행합니다. 실제 LLM·외부 수집을 사용한 평가는 이 검사와 구분합니다.

```bash
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests
npm --prefix frontend run build
```

구현이 바뀌면 담당 스펙과 SYSTEM을 갱신하고, 중요한 선택의 변경은 DECISIONS에 추가합니다.
이 문서는 주요 실행 경로와 선택 이유를 연결하는 역할을 유지합니다. 과거 결정은 덮어쓰지 않으며 개인 원문·실험 출력은 `logs/`에 둡니다.
