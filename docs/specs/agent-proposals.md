# 기획서 — 에이전트 제안함 (진화계획 3단계, 제안-전용)

> 2026-07-18. 상태: **기획 초안 — stakeholder 리뷰 대기.**
> 배경: D-023 "진화계획 3단계(자율 에이전트)" — 내러티브↔지식 루프(Phase 2 §2-5, 구현 완료)가
> 스스로 인과를 제안·검증·승격하는 토대는 깔렸다. 3단계는 이 위에서 **시스템이 스스로 "뭘 조사할지"
> 포착해 제안**하는 것. 2026-07-18 결정: **제안까지만 자동화, 실행은 항상 사람 승인 후**
> (D-020·D-022의 "기계는 제안, 사람은 승인" 원칙 그대로 계승 — 새 원칙 아님).

---

## 1. 핵심 재정의 — "자율"의 의미를 좁힌다

**아닌 것**: 에이전트가 스스로 판단해 리서치를 실행하거나, 메시지를 보내거나, 지식을 확정하는 것.
**맞는 것**: 지금까지는 사람이 먼저 "이거 봐봐" 해야 시스템이 반응했다면(질문형 대화, 수동 실행),
이제는 **시스템이 그래프·지식 상태를 스스로 감시하다가 먼저 "이거 조사해볼까요?"를 던진다.**
승인 전까지는 어떤 행동도 일어나지 않는다 — research_candidates·knowledge 승인 큐와 완전히 동일한
안전장치.

## 2. 이미 있는 재료 — 새로 발명하지 않는다

이번 조사에서 확인한 것: "기계 제안 → 사람 승인" 패턴이 이미 **3곳에 구현돼 있고, 그중 하나는 이미
여러 kind를 하나의 큐로 통합한 전례가 있다.**

- `ResearchProposalSection`(ExplorePage) — research_candidates, `proposed → done|dismissed`
- `KnowledgePage` 승격 큐 — knowledge, `review_status: proposed → active|rejected`
- **`ApprovalsCard`(HomePage)** — `/api/spine/approvals`가 이미 `kind`(alias|knowledge)로 서로 다른
  종류의 제안을 **한 카드 리스트에 통합**해서 보여주고 있다. "판단 루프 ③"이라는 주석까지 있음.

**결론**: 에이전트 제안함은 새 UI 패러다임이 아니라 **ApprovalsCard의 kind를 확장**하는 문제다.
BACKLOG.md에 이미 스펙되어 있던 두 항목(소외 스캐너·불편한 질문 브리핑)도 그대로 이 안에 흡수된다 —
따로 구현할 두 기능이 아니라, 이 통합 제안함의 첫 두 kind다.

## 3. 제안 종류 (kind) — v1 4종

| kind | 감지 로직 | 비용 | 승인 시 동작 |
|---|---|---|---|
| `neglect` | 밸류 스크린(저PER/PBR·건전 재무) ∩ 언급 부재 교차 (BACKLOG 기존 스펙) | LLM 0 | stock_brief(opus) 실행 |
| `contested_edge` | entity_relations `contested=true`인 엣지 쌍(Phase 2 §2-4에서 이미 계산됨) | LLM 0 감지, 승인 시만 opus | opus가 두 주장을 검토해 조정(confidence 재산정 또는 사용자 선택 요청) |
| `devils_advocate` | 내 watchlist/논지 vs 통념 반대 관점 질문 3개, 주 1회 (BACKLOG 기존 스펙, thesis_check 능동형) | haiku | 대화 스레드 시작 (또는 단순 확인만, §6 참고) |
| `falsifier_watch` | knowledge_falsifiers 중 미발화(`triggered_at IS NULL`)이고 근거 지식이 corroborated인 것 — "이 전제가 흔들리면 무엇이 달라지는지" 정기 리마인드 | LLM 0 | 확인만(액션 없음) — 다음 내러티브 재생성 시 이미 반증-우선 로직이 감시 중이므로 이건 순수 가시성 제공 |
| `entity_alias` (D-141 추가) | 대화 도구가 이름 해석을 '가정'으로 통과시킨 표기('삼양라면'→삼양식품) — `chat.generate_answer` 끝에 제안, dedup=`entity_id:표기` | LLM 0 | `entity_keywords(active)` 등록 → 다음부터 결정적 해석 |

**의도적으로 뺀 것**: 반복 질문 기반 트리거(product-v3.md L2 "질문의 cron화"). **이건 대화 영속화
(product-v3 L0/L1)가 먼저 있어야 한다 — 지금 conversations 테이블 자체가 없다.** 이 트랙의 전제
조건이지 이번 범위가 아님 (별도 트랙, 순서상 이 문서보다 먼저 필요할 수 있음 — §7 참고).

## 4. 데이터 모델

```sql
CREATE TABLE agent_proposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,        -- neglect|contested_edge|devils_advocate|falsifier_watch
    title         TEXT NOT NULL,        -- 제안형 한 줄 ("이 종목, 조사해볼까요?")
    rationale     TEXT,                 -- 왜 이걸 제안하는지 (사람이 승인 전 읽는 근거)
    payload_json  TEXT,                 -- kind별 구조화 데이터 (entity_id·edge_id·knowledge_id 등)
    status        TEXT DEFAULT 'proposed',  -- proposed|approved|dismissed|actioned
    detected_at   TEXT DEFAULT (datetime('now')),
    actioned_at   TEXT,
    result_json   TEXT                  -- 승인 후 실행 결과 요약
);
```

기존 `research_candidates`/`knowledge`는 그대로 두고 건드리지 않는다 — `agent_proposals`는 그 위에
얹는 **집계 레이어**다. `/api/spine/approvals`가 이미 kind별 다른 원본 테이블을 조회해 통합하고
있으므로, 같은 방식으로 `agent_proposals`도 그 kind 목록에 추가하거나(가벼움), 혹은
`agent_proposals` 자체가 유일한 원본이 되고 승인 시 `payload_json`을 바탕으로 대상 액션을
호출하는 방식(일관됨) 중 착수 시 결정 — 후자를 권장(신규 kind가 늘어날수록 approvals 라우터가
비대해지는 걸 방지).

## 5. 백엔드

- `pipeline/agent_proposals.py`(신규) — kind별 감지 함수 4개 + `run_all()` 배치.
- `scripts/scan_agent_proposals.py`(신규) — 주 1회 cron (promote_knowledge.py와 같은 주기 07:00
  또는 별도 슬롯).
- API: 기존 `/api/spine/approvals`에 kind 4종 추가, 또는 `/api/spine/agent-proposals` 신규
  (+ approve/dismiss).

## 6. 화면

- HomePage `ApprovalsCard`를 그대로 확장(신규 페이지 아님 — "판단 루프 ③"에 이미 있는 표면).
  kind별 아이콘·색만 구분(예: neglect=탐색, contested_edge=경고, devils_advocate=질문,
  falsifier_watch=시계).
- `devils_advocate`는 승인 시 "대화 시작"으로 연결하고 싶지만 대화 스레드가 미구현이므로, v1은
  **"확인" 버튼만**(체크 표시 후 dismiss와 동일 취급) — 대화 연동은 §7 트랙 완료 후 업그레이드.

### 5-state
| 상태 | 처리 |
|---|---|
| Empty | 4종 다 0건 — ApprovalsCard 자체를 숨김(기존 동작과 동일) |
| Loading | 기존 ApprovalsCard 스켈레톤 재사용 |
| Partial | 감지 배치 중 한 kind 실패해도 나머지 kind는 표시 |
| Error | 카드 조용히 생략 |
| Ideal | 4종 통합 표시 + 승인/기각 |

## 7. 선행 조건 / 의존성 (반드시 먼저 판단할 것)

- **product-v3.md L0(대화 영속화)** — `conversations`/`chat_messages` 테이블·API(`spine_conversations.py`)는
  이미 있다. 문제는 스키마가 아니라 **실사용 데이터량**(2026-07-18 기준 conversations 9건·
  chat_messages 28건) — 실서비스 중이 아니라 반복 질문 패턴을 감지·검증할 만큼 쌓이지 않았다
  (2026-07-18 stakeholder 확인). 3단계의 진짜 그림("사용자 질문 패턴이 에이전트의 할 일을 정의")은
  데이터가 쌓여야 완성된다 — 이번 v1(4종)은 대화 데이터에 의존하지 않는 부분집합으로 설계했고,
  반복 질문 기반 트리거는 실사용이 쌓인 뒤 재논의.
- **falsifier 감시의 구조화 필드 미사용** — 조사 중 발견: `knowledge_falsifiers`의
  `target_entity`/`metric`/`threshold`/`window`(D-022에서 추가)가 실제 `watch_falsifiers()`
  판정 로직에서는 쓰이지 않고 있다(문서 검색 텍스트만 사용). `falsifier_watch` kind를 제대로
  하려면 이 필드들을 실제로 활용하도록 `pipeline/falsifiers.py`를 먼저 손볼 여지가 있음 — 버그는
  아니지만 이번 트랙 착수 시 함께 검토 권장.

## 8. 구현 순서

1. `agent_proposals` 스키마 + `neglect`·`contested_edge` 2종 감지 함수(둘 다 LLM 0, 가장 쌈)
2. ApprovalsCard에 두 kind 통합 + 승인 시 액션(stock_brief 실행 / contested 조정 opus 호출)
3. `devils_advocate`·`falsifier_watch` 추가(haiku 비용 있음)
4. 주간 cron 편입 + SYSTEM.md 갱신
5. §7 의존성(대화 영속화) 착수 여부는 이 트랙 완료 후 별도 논의

## 9. Out of Scope (이번 v1)
- 반복 질문 기반 제안 (대화 영속화 선행 필요)
- 완전 자율 실행(승인 없는 액션) — 원칙적으로 이 프로젝트 전체 철학과 충돌, 재논의 없이는 안 함
- 제안 우선순위 랭킹/개인화(지금은 kind별 단순 리스트)
