# 대화(챗봇) 하네스 — 현황 분석 + 아키텍처 레퍼런스 (2026-09-08)

> 상태: 분석 완료 → **A 단계(D-130)·B 단계(D-131, docs/specs/chat-agent.md) 구현됨**. §5-D는 D-131에서 '기억해' 폐지·멀티턴 메모리(노트·상태·교차회상)로 대체 구현. C(검색 품질)는 D-132(docs/specs/chat-retrieval.md)로 구현됨 — A~D 전 단계 완료.
> 범위: `/chat` 웹 + 텔레그램 봇의 질의응답 경로 전체. 브리핑·내러티브 등 다른 LLM 산출물은 챗봇이 **소비하는 자산**으로만 다룬다.
> 관련: D-004(대화 프리미티브 승격) · D-009(LLM 계층) · D-117(effort low) · docs/specs/phase2-rag.md · product-v3.md §2 · PHILOSOPHY.md

---

## 0. 한 장 요약

지금의 챗봇은 **"하이브리드 검색 1회 → 프롬프트 1장 → sonnet 1콜 → JSON"** 인 고정 RAG 파이프라인이다. 2026-07에 P2-0~P2-2로 세팅한 뒤 하네스 개선은 없었다. 원칙(근거 없으면 거부·갭 일급·에코챔버 방지·영속화)은 잘 박혀 있으나, 그 위의 **하네스가 없다**:

- 챗봇이 닿는 자산은 `raw_documents` 본문 검색 하나. 그 사이 시스템에는 내러티브 294·인과 엣지 11,675·지식 71·질문 41·다이제스트 676·렌즈 판독 29·미국장 브리핑 18·리포트 9가 쌓였는데 **전부 챗봇 밖**이다.
- 실제 질문 로그 23건 중 상당수("최근 업데이트된 내러티브", "유튜브 컨텐츠 목록 최근순", "최근 유튜브 업데이트 있어?")가 **구조화 데이터 조회**인데 문서 검색으로 답하려 한다. 답이 안 나오니 안 쓰고(7월 14건 → 8월 1건), 안 쓰니 데이터가 안 쌓인다.
- LLM 호출 하네스 자체가 얇다: 시스템 프롬프트 없음, 구조화 출력 스키마 없음(문자열 슬라이싱 파싱), 도구 없음, 세션 없음, 비용·usage 기록 없음, 평가셋 없음, 스트리밍 없음.

레퍼런스(Anthropic·OpenAI·Google·Manus·Cognition·RAG 비교 논문)는 한 방향으로 수렴한다: **단일 에이전트 + 잘 설계된 도구 + 결정적 워크플로우를 먼저, 멀티에이전트는 나중(또는 안 함)**. 우리 스케일(1인·구독 LLM·SQLite)에는 정확히 맞는 처방이다. 제안 방향은 §5.

---

## 1. 현재 구조 (as-is)

### 1-1. 흐름

```
[웹 /chat]                                   [텔레그램 봇]
POST /api/spine/ask                           _poll_loop (데몬 스레드, long-polling)
 │ '기억해:' → inject_knowledge (동기, 즉시 답)  │ /start·/help·/briefing · 종목명(≤12자) → _stock_brief
 │ log_question → conversation_id 즉시 반환     │ '기억해:' → inject_knowledge
 └ BackgroundTasks(_generate_answer)           └ 문장(≥8자) → rag.ask(history)  ← **동기** (폴링 정지)
        │
        ├ '시나리오:' 접두어 → scenario.build_scenario (opus)
        └ rag.ask(question, history[-6])
              ├ search(prev_user_q + q, k=24)       ← BM25(FTS5) + 벡터(sqlite-vec, MiniLM 384d) RRF + 모달리티 쿼터
              ├ 뮤트 소스 제외 → 상위 16, 각 1,200자 발췌
              ├ recall_for_query (지식 ≤4, relevance×activation×epistemic)
              ├ quote_block (질문 속 종목 실시간 시세 ≤3)
              ├ lens_block (패턴·산업·세계관 렌즈 3종 **항상 전부**, 1,851자)
              └ 프롬프트 1장 → `claude -p --model sonnet --output-format json` (timeout 300s)
                    → raw.find('{')…rfind('}') 슬라이싱 → {answer, citations[], gaps[]}
              → append_assistant(citations_json, gaps_json, model)
[FE] 마지막 메시지=user ⇒ 2.5초 폴링 · AnswerWatcher 8초 폴링(다른 화면 토스트)
```

### 1-2. 파일 지도

| 층 | 파일 | 역할 |
|---|---|---|
| 라우터 | `backend/routers/spine_ask.py` (114) | 접두어 라우팅 3종(기억해/시나리오/RAG) · 비동기 적재 |
| 라우터 | `backend/routers/spine_conversations.py` (108) | 스레드 목록(종목 필터·오너 필터)·상세 |
| 엔진 | `backend/pipeline/rag.py` (145) | 검색→프롬프트→claude -p→파싱 |
| 검색 | `backend/pipeline/search.py` (184) | 하이브리드 검색·인덱스 빌드·관련 문서 |
| 컨텍스트 | `knowledge_recall.py`·`lenses.py`·`quotes.py` | 지식 소환·렌즈·시세 블록 |
| 영속화 | `backend/pipeline/conversations.py` (155) | conversations/chat_messages/chat_entity_links, 텔레그램 30분 스레딩 |
| 봇 | `backend/pipeline/bot.py` (429) | 텔레그램 폴링·라우팅·딥링크 액션·HTML 렌더 |
| FE | `components/chat/ChatPage.tsx` (252) · `layout/AnswerWatcher.tsx` · `summary/AskedSection.tsx` | 스레드 UI·전역 답변 도착 감시·도시에 "내가 물어본 것들" |

### 1-3. 데이터 (2026-09-08 실측)

| 자산 | 행수 | 챗봇 접근 |
|---|---|---|
| raw_documents | 16,119 | ✅ 본문 검색 (유일한 경로) |
| knowledge (승격 지식) | 71 | △ 질의 유사도 ≥0.45 상위 4건만 |
| entity_relations (인과 엣지) | 11,675 | ❌ |
| narratives (버전 포함) | 294 | ❌ ('시나리오:' 접두어만 별도 엔진) |
| entity_digests (1D/1W/1M) | 676 | ❌ (봇 종목명 조회에서만 1D 최신 1건) |
| signals | 13,157 | ❌ (봇 종목명 조회에서만 최신 1건) |
| questions / sub_questions | 41 / 99 | ❌ |
| lens_readings · us_briefings · reports · stock_briefs · scenarios · doc_syntheses | 29·18·9·100·19·5 | ❌ |
| stock_prices · consensus · financials (옛 세계) | 71만+ | ❌ (실시간 시세 3종목만 quote_block) |

대화 데이터: **conversations 15 · chat_messages 46 · 사용자 질문 23** (web 11 / telegram 4). 월별 7월 14건, 8월 1건. 스레드 길이 2·4·6 메시지. product-v3 §4 리스크 가정 A1~A3("질문 빈도")는 현재 데이터로는 **부정 쪽**이다 — 단 원인이 "대화가 필요 없어서"인지 "답을 못 해서"인지는 로그가 후자를 가리킨다(§2-1).

---

## 2. 진단

### 2-1. 자산 접근성 — 챗봇이 시스템의 5%만 본다 (가장 큰 문제)

실제 질문 23건을 유형별로 보면:

| 유형 | 예 | 지금 처리 | 필요한 것 |
|---|---|---|---|
| 구조 조회 | "최근 업데이트된 내러티브", "유튜브 목록 최근순", "최근 유튜브 업데이트 있어? 삼성증권 텍톡" | 문서 본문 검색 → 엉뚱한 발췌 or "문서 없음" | narratives/raw_documents(source=youtube, channel) **SQL 조회 도구** |
| 사건 설명 | "하이닉스 오늘 코스피에서 빠지는 이유?" | 검색 16건 | 검색 + **당일 시세·신호·기업활동** + 최신 내러티브 |
| 종합 분석 | "ADR 상장이 코스피 하이닉스 주가에 미칠 영향" | 검색 16건 + 지식 4 | 검색 + **인과 그래프(월드모델)** + 질문 트래커 + 렌즈 판독 |
| 인물 서사 | "아모데이·알트먼 관계" | 검색 (canon 소스 있으면 답) | 검색 + people 엔티티 |
| 후속질문 | "방금 답변에서 가장 중요한 부분?" | history 6개 400자 절단 | 스레드 컨텍스트 (현행 OK) |
| 명령 | "기억해: …" | 접두어 매칭 | 현행 OK, 단 §2-4 |

라우팅이 **접두어 문자열 3종**(`기억해`·`시나리오`·나머지)이라 나머지 전부가 문서 RAG로 떨어진다. Anthropic의 "Building effective agents"가 첫 번째 워크플로우 패턴으로 꼽는 **Routing**(입력 분류 → 전용 경로)이 없고, Agent SDK 문서가 지식베이스 어시스턴트의 핵심으로 말하는 **도구(searchDocuments 류)** 가 하나도 없다.

### 2-2. 컨텍스트 조립 — 질문 유형 무관 고정 (정적·과잉)

매 질문에 들어가는 것: 문서 16×1,200자(≈19K자) + 렌즈 3종 전부(1,851자) + 지식 ≤4 + 시세 + history. Anthropic 컨텍스트 엔지니어링 원칙("결과 확률을 최대화하는 **최소 고신호 토큰 집합**")과 반대로, 종목 질문에도 세계관 렌즈가, 목록 조회에도 문서 16건이 들어간다. 반대로 정말 필요한 것(인과 엣지·최신 내러티브)은 안 들어간다. 후속질문 검색어는 직전 사용자 질문 + 현재 질문 단순 접합 — 쿼리 재작성 없음.

### 2-3. LLM 호출 하네스 — 원시 subprocess, 15곳 중복

`claude -p` subprocess가 `rag.py` 포함 **15개 모듈에 각각 복제**돼 있다(공용 러너는 `enrich._call_claude_code` 하나, 나머지는 자체 호출). 챗봇 경로 기준 결손:

| 항목 | 현행 | 가능한 것 (claude 2.1.263 실측 플래그) |
|---|---|---|
| 시스템 프롬프트 | 없음 — 규칙·렌즈·지식·문서·질문이 **한 user 프롬프트**에 | `--append-system-prompt`(안정 prefix: 역할·규칙·렌즈) + user(질문·근거) 분리. Manus "KV-cache 안정 prefix" 원칙 |
| 구조화 출력 | `--output-format json` 후 `raw.find('{')`로 슬라이싱 | `--json-schema` → `structured_output` 필드. 파싱 실패 클래스 제거 |
| 도구 | 없음 (그러나 `--tools` 미지정이라 Claude Code 기본 도구가 로드됨 — 모델이 Bash/Read를 쓸 수 있는 상태) | `--tools ""`로 차단하거나, 역으로 `--mcp-config`+`--strict-mcp-config`로 **우리 DB 도구만** 노출 |
| 세션 | 매 콜 새 세션, history 텍스트 재주입 | `--resume <session_id>`(json 응답의 `session_id` 저장) — 스레드=세션 매핑 가능. 단 프로젝트 컨텍스트 로드 비용 고려 |
| 비용·usage | 기록 없음 | json 응답에 `usage`·`total_cost_usd` 포함 — `llm_calls` 테이블에 적재하면 D-117식 실측이 상시화 |
| 스트리밍 | 없음 (30~150초 스켈레톤) | `--output-format stream-json --include-partial-messages` → SSE. 웹은 폴링 구조를 유지하고 봇만 생략도 가능 |
| effort | 기본 | 라우터·분류는 `--effort low`(D-117), 종합만 기본 |
| `--bare` | 불가 (키체인 인증, D-106·D-117) | 변동 없음 — 대신 시스템 프롬프트를 우리가 주고 도구를 좁혀 기동 컨텍스트를 줄인다 |

### 2-4. 메모리 계층 — 단기·장기·프로필이 한 통

- **단기**(스레드): 최근 6문답, 답변 400자 절단. 스레드가 길어지면 요약(compaction) 없이 잘린다.
- **장기 시장 지식**(`knowledge`): '기억해:'로 주입 → activation×epistemic 소환. 설계는 좋다.
- **사용자 프로필/선호**: 없음. 로그에 "기억해: 이 시스템을 만든 사람은 김주영이다"가 **시장 지식 테이블**에 들어가 있다 — 종류가 다른 기억이 한 통에 섞인 실증. Google ADK(Session/State/Memory 3층 분리)·Letta(core/recall/archival)·LangChain(episodic/procedural/semantic)이 공통으로 나누는 축.
- **대화에서 지식 자동 추출**: 없음. Mem0·Memory Bank식 "세션 → 추출·통합(ADD/UPDATE/DELETE)"은 우리 원칙상 **제안 큐 경유**(PHILOSOPHY §4 제안-전용)여야 한다 — `agent_proposals`에 kind 추가로 자연스럽게 붙는다.

### 2-5. 검색 품질 — 16,119건인데 Phase-2 초기 구성 그대로

phase2-rag.md가 "남은 것"으로 적어둔 항목이 그대로 남아 있다: 청킹(문서 단위 임베딩, 제목+2,000자만), 엔티티/기간/소스 필터와 벡터 결합, 리랭커. Anthropic Contextual Retrieval 실측(청크 컨텍스트 + BM25 → 실패율 −49%, +리랭킹 −67%)과 RAG 비교 논문(리랭킹은 **고정 모듈**이 에이전트보다 낫다)이 모두 이 결손을 가리킨다. 컨콜 transcript처럼 긴 문서는 2,000자 이후가 임베딩에서 사라진다.

### 2-6. 신뢰성 버그·취약점 (코드 근거)

1. **텔레그램 경로가 동기** — `bot.py` `_poll_loop`가 `handle_message` → `rag.ask()`를 폴링 스레드에서 직접 실행. 30~150초 동안 다른 메시지·딥링크 처리가 멈춘다. 딥링크 액션(`start_action`)은 이미 데몬 스레드로 뺐는데 RAG만 남았다.
2. **user-only 스레드 → 웹 UI 영구 '생성 중'** — 봇이 "관련 수집 문서가 없어" 또는 "찾지 못했습니다"를 돌려줄 때 `log_exchange_safe(q, None, …)`로 **사용자 메시지만 적재**한다. 웹 `ChatPage`는 "마지막 메시지=user"를 생성 중으로 해석해 2.5초 폴링 + 컴포저 비활성이 **영원히** 지속된다(오너 텔레그램 스레드는 웹 목록에 뜬다). 현재 DB에는 짝수 길이 스레드만 있어 발현 전이지만 경로는 열려 있다. 같은 이유로 서버가 백그라운드 태스크 중 죽으면 웹 스레드도 같은 상태에 빠진다 — FE에 상한(예: 5분) 없음.
3. **JSON 파싱 취약** — 모델이 `answer` 마크다운 안에 `}`를 쓰면 `rfind('}')`는 맞지만 `find('{')` 앞에 설명 문장이 붙는 경우 등 실패 클래스가 남아 있다(→ `--json-schema`).
4. **인용 검증 없음** — `citations` 인덱스 범위만 확인. 답변 본문의 `[n]`이 `citations`에 없거나, 인용 없는 단정 문장이 있는지 코드로 검사하지 않는다. Agent SDK 문서의 "rules-based verification"(인용 정확성은 규칙으로 검사 가능한 대표 사례)에 해당.
5. **평가 부재** — 골든 질문셋·회귀 스크립트 없음. 프롬프트를 바꿔도 좋아졌는지 알 길이 없다.

### 2-7. 잘 돼 있는 것 (유지)

- 정직 원칙의 코드화: 근거 없으면 거부, 갭 4종 일급 출력, 답변=가설 UI, 뮤트 소스 제외를 근거에도 적용.
- **에코챔버 방지 불변**(D-004 ③): 답변은 인덱스에 안 들어간다 — 유지.
- 진행 상태가 서버 상태(질문 즉시 적재 → 폴링): 1인 스케일에 맞는 단순함. 탭 이동·새로고침 내성.
- 웹·텔레그램 공용 스레드 풀 + chat_id 프라이버시 격리(A7).
- 지식 소환 랭킹(relevance×activation×epistemic + pace layer 힌트)과 내부 코드 비노출 규율.
- 실시간 시세 주입(낡은 종가로 답하지 않기).

---

## 3. 아키텍처 레퍼런스 리서치

### 3-1. Anthropic

| 소스 | 핵심 | 우리 적용 |
|---|---|---|
| **Building effective agents** (2024-12) | 워크플로우 5패턴(프롬프트 체이닝·**라우팅**·병렬·오케스트레이터-워커·평가자-최적화자) vs 에이전트. "예측 가능한 구조면 워크플로우, 스텝 수를 예측 못 하면 에이전트". 도구 설계(ACI)에 프롬프트만큼 투자 | 1단계는 **라우팅 워크플로우**. 열린 종합 질문만 제한된 에이전트 루프 |
| **Effective context engineering for AI agents** (2025-09) | 컨텍스트=한정 자원, "최소 고신호 토큰". 시스템 프롬프트는 XML/MD 섹션으로 "적절한 고도". **Just-in-time**: 식별자만 들고 도구로 필요할 때 로드. 컴팩션·구조화 노트·서브에이전트(1~2K 토큰 요약 반환) | 렌즈·문서를 전부 선적재 → 라우터가 고른 것만. 문서는 id·제목만 주고 `open_doc` 도구로 |
| **Building agents with the Claude Agent SDK** (2025-09) | 루프 = 컨텍스트 수집 → 행동 → **검증**. 지식베이스 어시스턴트엔 `searchDocuments` 류 도구가 1급. 검증 3종: 규칙(인용 정확성) · 시각 · LLM 판정 | 인용 검증을 규칙으로. 도구형 검색 |
| **Multi-agent research system** (2025-06) | 오케스트레이터-워커 + 인용 에이전트 분리. **노력을 질문 복잡도에 비례**(단순 질의: 1에이전트 3~10콜). 멀티에이전트는 채팅 대비 토큰 **15배**. 평가는 20케이스로 즉시 시작, LLM 판정 0~1 단일 점수. 넓게 시작 → 좁히기 | 병렬 서브에이전트는 우리 예산에 부적합. 복잡도 비례 예산·소규모 평가는 채택 |
| **Contextual Retrieval** (2024-09) | 청크 앞에 50~100토큰 문맥(haiku) → 임베딩+BM25. 실패율 5.7→2.9%(−49%), 리랭킹 추가 1.9%(−67%). top-20 > top-5/10 | 청킹 + 문맥 생성(haiku `--effort low`, 문서당 1회 캐시 = D-117 패턴) + 로컬 리랭커 |
| **Demystifying evals for AI agents** (2026-01) | 능력 eval(낮은 통과율에서 시작) vs 회귀 eval(~100% 유지). 코드 채점·모델 채점·사람 채점. **실제 실패 20~50건에서 시작**, 트랜스크립트를 읽어라 | 실제 질문 23건 + 실패 사례로 첫 셋 |
| **Effective harnesses / Harness design for long-running app dev** (2025-11 · 2026-03) | 초기화자/실행자 분리, 진행 파일·기능 목록=외부 메모리, 세션 핸드오프 프로토콜, Generator-Evaluator 쌍 | 우리 "대화=DB 상태"가 이미 이 방향. 스레드 컴팩션 노트를 DB에 |
| **Claude Code headless 문서** (현행) | `--append-system-prompt`·`--json-schema`(`structured_output`)·`--resume`/`session_id`·`--mcp-config`+`--strict-mcp-config`·`--tools`·`stream-json`·json에 `usage`/`total_cost_usd`. `--bare`는 API 키 필요 | §2-3 표 그대로. `--max-turns`는 이 버전 help에 없음(예산은 `--max-budget-usd`만 — 구독 인증에선 의미 확인 필요) |

### 3-2. OpenAI

- **Agents SDK / Responses API**: 프리미티브를 의도적으로 적게 — Agent·Runner·Tools·Handoffs·**Guardrails**(입출력 검증, 에이전트와 병렬 실행·tripwire)·**Sessions**(대화 히스토리 영속). Assistants API는 2026-08 종료.
- **A practical guide to building agents**: "**단일 에이전트+도구로 시작**, 한계에 부딪힐 때만 매니저 패턴 → 분산 핸드오프". 가드레일은 층(입력 검증·도구 제약·출력 필터·토큰 상한). 사람 개입 트리거: 고위험·이상 패턴·예산 초과·저확신.
- 적용: 우리 `gaps`가 곧 출력 가드레일의 씨앗. "인용 없는 단정"을 tripwire로 승격. 텔레그램=웹과 같은 Runner를 타되 채널 어댑터만 다르게(지금은 봇이 `ask()`를 직접 호출해 웹의 비동기 경로와 갈라져 있다).

### 3-3. Google

- **ADK**: LLM 에이전트 + **워크플로우 에이전트(Sequential/Parallel/Loop)** = 결정적 오케스트레이션을 1급으로. **Session(단기 대화) / State(작업 변수) / Memory(장기, Memory Bank)** 3층 분리. evalset 기반 평가 내장. 콜백 훅.
- **Memory Bank**: 세션 이벤트 → 추출·**통합**(consolidation) → 유사도 검색으로 소환. 리비전 추적.
- 적용: §2-4 메모리 3층 분리의 참조 모델. 단 자동 통합은 우리 원칙상 제안 큐 경유.

### 3-4. 기타 AI 엔지니어링 (Manus · Cognition · LangChain · 논문)

- **Manus "Context Engineering for AI Agents"**: KV-cache 적중률이 1순위 지표(안정 prefix, 타임스탬프 금지, append-only) · 도구는 제거 말고 **마스킹** · **파일시스템=컨텍스트**(내용은 버리고 경로/URL만 남겨 복원 가능하게) · todo 낭독으로 주의 조정 · **실패 흔적을 남겨라** · few-shot 패턴 고착 주의.
  - 적용: 시스템 프롬프트 고정 + 질문마다 변하는 것(날짜·시세)은 user 쪽으로. 문서는 id로 참조하고 도구로 열기. 실패 답변(`답변 생성 실패`)도 스레드에 남기는 현행은 옳다.
- **Cognition "Don't build multi-agents"**: 컨텍스트를 **전부 공유**하라, 행동엔 암묵적 결정이 실려 있다 → 병렬 서브에이전트는 결정이 충돌한다. **단일 스레드 선형 에이전트** + 긴 작업은 전용 압축 모델. 
  - 적용: 우리 스케일의 정답. 챗봇은 단일 루프, 스레드 길어지면 haiku 압축 노트.
- **LangChain "Context engineering"**: Write(스크래치패드·메모리) / Select(RAG·도구 선택) / Compress(요약·트리밍) / Isolate(서브에이전트·샌드박스·상태 스키마) 4분류. 진단 체크리스트로 유용.
- **"Is Agentic RAG worth it?" (arXiv 2601.07711, 2026-01)**: Naïve / Enhanced(고정 모듈: 라우팅·재작성·리랭킹) / Agentic 비교(NQ·FIQA[금융]·FEVER·CQADupStack). **라우팅·쿼리 재작성은 에이전트가 유리**(+2.8 NDCG@10), **리랭킹은 고정 모듈이 유리**, 에이전틱 반복 재검색의 53%는 같은 문서를 다시 가져옴. 비용: 입력 3.3배·출력 1.9배·지연 1.5배. 결론: **하이브리드** — 에이전트는 라우팅/재작성 판단만, 리랭킹은 결정적 모듈.
  - 적용: §5 설계의 핵심 근거. 우리 문서 검색은 결정적 파이프라인(하이브리드 → 리랭커)으로 두고, 모델은 "어느 도구를 어떤 쿼리로" 만 결정.
- **Letta/MemGPT · Mem0**: core(항상 로드) / recall(대화 검색) / archival(도구로 조회) 3층. 추출→ADD/UPDATE/DELETE/NOOP. LongMemEval 등 벤치.

### 3-5. 수렴하는 결론

1. **라우팅 먼저, 에이전트는 좁게** — 분류 가능한 질문은 전용 경로, 열린 종합만 제한 루프.
2. **도구가 컨텍스트다** — 선적재 대신 식별자+도구. 지식베이스 어시스턴트의 1급 인터페이스는 `search_*`/`get_*` 도구.
3. **결정적 모듈과 모델 판단을 나눈다** — 리랭킹·인용 검증·시세·SQL은 코드, 재작성·라우팅·종합은 모델.
4. **메모리 3층 분리** — 세션 / 사용자 프로필 / 시장 지식.
5. **측정 없이 바꾸지 않는다** — usage 기록 + 실제 질문 기반 소규모 평가셋. D-117이 이미 준 교훈.
6. **멀티에이전트 병렬은 우리 예산·정합성에 맞지 않는다** — 단일 스레드 + 압축.

---

## 4. 원칙 정합성 점검 (PHILOSOPHY.md)

| 원칙 | 제안 방향과의 관계 |
|---|---|
| 사실/가설 분리 | 도구가 반환하는 것에 `epistemic`·출처를 실어 모델이 그대로 표기. 인과 엣지는 confidence 동반 |
| 정직이 정밀을 이긴다 | 근거 거부 원칙 유지. 도구가 늘어도 "도구 결과 밖의 단정 금지" — 인용 검증을 규칙으로 |
| 기계는 제안·사람은 판단 | 대화에서 지식·프로필 자동 추출은 **제안 큐**로만. 답변이 상태를 바꾸지 않음(예외: 명시 '기억해') |
| 에코챔버 방지(D-004 ③) | 유지. 답변·압축 노트는 인덱스 밖 |
| 비용 의식(memory `cost-conscious-design`) | 라우터·압축은 haiku+`--effort low`, 종합만 sonnet. 콜당 usage 기록으로 상시 실측 |
| 내부 코드 비노출 | 시스템 프롬프트에 no-leak 규칙 고정(현행 knowledge_block 규율을 승격) |

---

## 5. 제안 방향 (후보 — 결정 아님)

우선순위는 "챗봇이 답할 수 있는 것을 늘린다(§2-1)" > "하네스 기초(§2-3·2-6)" > "검색 품질(§2-5)" > "메모리(§2-4)". 각 단계가 독립 가치·독립 롤백.

### A. 하네스 기초 (저위험, 선행)
- **A1 공용 LLM 러너** `pipeline/llm.py`: `run(prompt, *, system, model, schema, effort, tools, timeout)` → `--append-system-prompt`·`--json-schema`·`--tools`·usage/cost 파싱. `llm_calls` 테이블(job·model·in/out/thinking 토큰·cost·소요·ok). 챗봇부터 적용, 다른 14곳은 점진 이관(단 이번 범위 밖).
- **A2 텔레그램 비동기화 + user-only 스레드 수정**: 봇도 웹과 같은 "질문 적재 → 백그라운드 생성 → 결과 발송(D-111 말풍선 대체)" 경로. 무응답 케이스는 assistant 메시지로 적재. FE 폴링 상한(5분 후 "생성이 멈춘 것 같습니다 · 다시 시도").
- **A3 평가셋 v0**: 실제 질문 23건 + 유형별 보강 → 20~30건. 채점: 규칙(인용 유효·거부 정확·유형별 필수 도구 호출) + haiku 루브릭 0~1. `scripts/eval_chat.py` — 프롬프트 변경마다 실행.
- **A4 인용 검증 규칙**: 본문 `[n]` ⊆ citations, 인용 0건인 단정 문장 수 → `gaps(unsupported)` 자동 보강.

### B. 라우터 + 도구 (핵심)
- **B1 의도 라우터**(haiku, `--effort low`, json-schema): `{intent: lookup|event|synthesis|person|followup|command, entities[], time_range, tools[]}`. 결정적 선처리(종목명·'기억해'·'시나리오')는 유지.
- **B2 도구 세트**(읽기 전용, 각각 epistemic·출처 동반):
  `search_docs(q, source?, entity?, since?)` · `open_doc(id)` · `list_recent(kind=narratives|digests|youtube|signals|actions, entity?, n)` · `get_narrative(topic)` · `get_worldmodel(entity)`(인과 엣지 양방향+걸린 내러티브, LLM 0 — 기존 `/us/{ticker}/worldmodel` 로직 재사용) · `get_knowledge(q)` · `get_questions(entity?)` · `get_lens(code, market)` · `get_quote(code)` · `get_regime()`.
  전부 기존 라우터/파이프라인 함수의 얇은 래퍼 — 새 로직 최소.
- **B3 실행 방식 — 두 옵션 (열린 질문 ①)**:
  - (i) **Python 오케스트레이션**: 라우터 출력대로 Python이 도구를 실행해 컨텍스트 조립 → 종합 1콜. 결정적·저비용(콜 2회)·관측 쉬움. Anthropic "라우팅 워크플로우"·논문의 "Enhanced" 그대로. **추천 시작점.**
  - (ii) **MCP 도구를 `claude -p`에 노출**(`--mcp-config`+`--strict-mcp-config`+`--allowedTools mcp__explorer__*`, `--tools`로 기본 도구 차단): Claude Code 하네스가 루프·도구 호출을 담당 → 진짜 에이전틱(재검색·재작성 가능). 코드는 적지만 턴 수·비용 통제 수단이 약함(`--max-turns` 부재). synthesis 인텐트에만 한정 적용하는 절충 가능.
- **B4 시스템 프롬프트 분리**: 역할·정직 규칙·no-leak·출력 스키마·(라우터가 고른) 렌즈 1종 → `--append-system-prompt`. user에는 질문·도구 결과·날짜·시세.

### C. 검색 품질
- **C1 청킹 + 문맥 생성**(Contextual Retrieval): 1,500자 청크, haiku low로 50~100토큰 문맥, `doc_chunks`·`chunk_vec`. content_hash 멱등(D-117 패턴). 긴 소스(transcript·youtube 정리본)부터.
- **C2 로컬 리랭커**: 다국어 cross-encoder(예: bge-reranker-v2-m3) — 후보 40 → 상위 12. LLM 0.
- **C3 필터 결합**: 라우터의 entity/time_range를 FTS·벡터 후보에 사전 필터(entity_links·published_at).
- **C4 후속질문 쿼리 재작성**: 라우터가 `followup`이면 독립 검색어 생성(논문: 재작성은 모델 판단이 유리).

### D. 메모리 계층
- **D1 '기억해' 분기**: 시장 지식(knowledge) vs 사용자 프로필(`user_memory`: 선호·역할·관심 유니버스) — 라우터가 분류, 애매하면 사용자에게 되묻기.
- **D2 스레드 압축**: 6문답 초과 시 haiku low로 압축 노트(`conversations.summary`), history는 노트+최근 2문답. 인덱스 밖.
- **D3 대화→지식 후보 제안**: 사용자 발언 중 판단·가설을 `agent_proposals(kind=knowledge_from_chat)`로 — 승인 시 knowledge 주입(product-v3 §2-5 "판단 승격"의 자동화된 절반).

### 기각·보류 후보
- **병렬 멀티에이전트 리서치**(오케스트레이터-워커): 토큰 15배·결정 충돌(Cognition). 1인 구독 예산에 부적합. 보류.
- **세션 `--resume`로 히스토리 대체**: Claude Code 세션은 프로젝트 컨텍스트를 함께 로드해 prefix가 커지고, 우리 DB가 이미 진실원천. 채택 안 함(스트리밍·재시도에만 session_id 활용 가능).
- **전 호출 `--effort low`**: D-117 (a) 기각 사유 동일.
- **답변 인덱싱**: D-004 ③ 불변.

---

## 6. 열린 질문 → 결정 (2026-09-08, D-130)

1. **B3 실행 방식**: Python 오케스트레이션 직접 구축(LangGraph 기각 — subprocess 어댑터를 어차피 직접 쓰고 워크플로우가 짧다). 상태 dataclass+단계 함수 형태 유지로 이관 비용 최소화.
2. **킬 기준**: 폐기 — 측정기(질문 빈도)가 챗봇이 답을 못 낸 상태에서 잰 값.
3. **스트리밍**: 도입 — 토큰 비용 동일(조각 전달), 연결 1개/생성. 단계 status + 본문 delta.
4. **평가 채점**: 사용자가 baseline run md를 채점.

(아래는 결정 전 원문)

### 6-0. 원 질문

1. **B3 실행 방식**: (i) Python 오케스트레이션(결정적, 추천 시작점) vs (ii) MCP 도구 노출로 Claude Code 루프에 맡기기 vs (i)로 시작해 synthesis만 (ii) 절충.
2. **사용 빈도**: 대화 15건은 product-v3 킬 기준(A1~A3 부정 시 봇+옴니바 수준으로 롤백)에 가깝다. "답을 못 해서 안 썼다"는 가설에 동의하면 §5-B가 그 검증 실험이 된다 — 진행 여부 확인.
3. **스트리밍**: 웹 폴링 유지 + 봇 말풍선 대체로 충분한가, 아니면 SSE 스트리밍까지 가는가(A4와 별개).
4. **평가 채점자**: 루브릭 채점의 기준 답은 도메인 전문가(사용자) 판정이 필요 — 20~30건 한 번 채점해줄 수 있는가.
5. **범위**: A1 공용 러너를 챗봇 외 14개 모듈까지 이관할지(별도 작업으로 분리 권장).

---

## 참고 링크

- Anthropic: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) · [Building agents with the Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk) · [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) · [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) · [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) · [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) · [Engineering blog 인덱스](https://www.anthropic.com/engineering) · [Claude Code headless 문서](https://code.claude.com/docs/en/headless)
- OpenAI: [Agents SDK](https://openai.github.io/openai-agents-python/) · [A practical guide to building agents (PDF)](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) · [New tools for building agents](https://openai.com/index/new-tools-for-building-agents/)
- Google: [ADK](https://adk.dev/) · [Memory Bank overview](https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/overview) · [agent-design-patterns 카탈로그](https://github.com/kweinmeister/agent-design-patterns)
- 기타: [Manus — Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) · [Cognition — Don't Build Multi-Agents](https://cognition.com/blog/dont-build-multi-agents) · [LangChain — Context Engineering for Agents](https://www.langchain.com/blog/context-engineering-for-agents) · [Is Agentic RAG worth it? (arXiv 2601.07711)](https://arxiv.org/abs/2601.07711) · [Mem0 vs Letta](https://vectorize.io/articles/mem0-vs-letta) · [awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering)
