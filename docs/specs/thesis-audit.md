# 논지 감사 — 내 thesis를 축적된 인과그래프에 대질 (thesis audit)

> 2026-07-28 기획 (대화 2026-07-28). 배경: 시스템이 지능화되며 "내 고차원 thesis를 그대로 주입해 리포트/질문
> 퀄리티로 검토받을 수 있나?"라는 요구 발생. 문제의식: **그냥 다중 에이전트 토론을 붙이면 ChatGPT와 다를 바 없다**
> — 토론(추론)은 프런티어 LLM이 이미 한다. 이 시스템의 moat는 추론이 아니라 **축적된·출처달린·시간찍힌·교차검증된
> 인과그래프에 정박시키고 반증으로 추적하는 것**.
>
> 실측 프로브(2026-07-28)로 de-risk 완료: 예시 thesis(AI 인프라 사이클)의 각 주장이 이미 그래프에 있었다 —
> `OpenAI→상장 연기`(2독립·conf0.80), `OpenAI→모델레이어 수익성 논쟁`(effect_direction=**negative**), 내러티브
> `AI v8`("AI 지출 실물화는 유동성 회수보다 빠를까"), 시간축서 OpenAI 언급 2026-07에 6배 급증("최근 본격화" 검증).
> 이 손작업을 자동화·심화하는 것이 본 기능.

## 관통 원칙 (비타협)

1. **감사(audit)지 등재가 아니다 — read-only 기본.** 네 주장을 그래프에 *쓰는* 게 아니라 그래프에 *비춰* 델타를 본다.
   "매핑"은 두 연산(읽기 vs 쓰기)이고 섞으면 안 된다. 기본 경로는 SELECT만, 온톨로지 무변경.
2. **moat는 정박이지 토론이 아니다.** 산출물의 **모든 문장이 코퍼스 포인터**(엣지 id·독립 소스 수·created_at·프록시
   관측치·내러티브 버전)를 가리켜야 한다. ChatGPT에 붙여넣어 나올 문장이 하나라도 있으면 그 부분은 실패. LLM 종합은
   맨 위 얇은 층, 몸통은 grounding.
3. **사실/가설 분리 — 물질화는 선택이고 격리된다 (PHILOSOPHY §1).** 쓰기를 택하면 `epistemic_type=hypothesis`·
   `source=user`·confidence 상한(≤0.5, scenario D-028 선례)·**반증조건 자동 생성**·**승인 게이트**(D-020). 그리고
   **자기 교차검증 금지** — 사용자 주입 엣지는 corroborated_by 집계에서 제외(독립성 불변식). 자기확증 에코챔버 차단.
4. **정직한 공백 (§3 거짓 정밀 회피).** 그래프에 없으면 `novel`로 표시하고 LLM 프라이어로 메워 "확인됨"인 척 하지
   않는다. 코퍼스가 얇으면 그 사실을 노출한다 — 이게 ChatGPT로 후퇴하는 정확한 지점이므로 명시.

## 산출 = 델타 (등재가 아니라 감사)

핵심 출력은 "네 thesis가 진실로 등록됨"이 아니라 **너와 그래프 사이의 델타**:
- **일치(aligned)** — 그래프가 이 주장을 지지(엣지 존재·conf·독립 소스). "네 확신 ✓ 근거 있음"
- **충돌(contested)** — 반대 방향 CAUSES 엣지 공존 / contested 플래그. "조심 — 축적된 반례"
- **신규(novel)** — 그래프에 없음. "네가 앞서거나, 코퍼스가 얇거나"
- **선반영(priced-in)** — 진자(salience×conviction) 과열. "이미 붐빔 — 늦었을 수도"
- **회고 vs 최근(temporal)** — 그 주장이 오래된 것인가 최근 급증인가(시간 검증).

## 파이프라인 (5 stage)

**① 논지 분해 (decompose)** [sonnet] — 자유서술 thesis → 원자 주장(claim)들 + 각 주장의 **역할 태그**(사용자가
어떻게 프레임했나: `consensus`/`shift`/`catalyst`/`causal`/`synthesis`) + **주장된 인과 구조**(주원인 vs 부차/증폭 —
예: "인프라 흔들림=주, 중국=부채질"). 질문 트래커 `decompose_question`(D-067) 기계 재사용, 산출이 sub-question이
아니라 claim일 뿐.

**② 그래프 정박 (ground)** [LLM 0 + 의미검색] — 주장마다:
- **엔티티 해소** → claim의 주체/객체를 vocab으로 entity_id 해소(`resolve_and_enrich` 패턴).
- **매칭 인과 엣지** → 그 엔티티를 잇는 `entity_relations`(CAUSES/BENEFITS_FROM) 후보 + mechanism 의미유사 필터.
  반환: epistemic_type·confidence·**corroborated_by**(narrative_edge_evidence 독립 내러티브 수)·**contested**(반대엣지)·
  effect_direction/strength·created_at·reference_period·geo_scope.
- **매칭 내러티브** → 그 주장을 다루는 narratives(+version·drift_summary).
- **시간 검증** → claim 개념의 월별 문서수(결정적) → 급증(spike) 감지 = "최근 본격화" 류 검증.
- **주장별 판정**: aligned/contested/novel/stale-vs-fresh.

**③ 진자 위치 (pendulum)** [LLM 0] — 핵심 주장의 앵커 엔티티에 `knowledge_state`(salience×conviction, 설계 §G)
적용 → 선반영/기회/진자경고/노이즈 4상 위치. "이미 시장이 다 아는가"의 계량.

**④ 반증조건 + 프록시 배선 (falsifiers + proxies)** [sonnet] — thesis의 반증조건 생성(반증-우선 §4) + 관측
프록시 배선(하이퍼스케일러 CAPEX·OpenAI 자금조달 등, transcript 프록시 D-067). → 선택 시 **추적되는 핵심질문**을
스폰(사용자 가설로 격리 태그). thesis가 일회성 답이 아니라 **앞으로 추적**되게.

**⑤ 종합 (grounded synthesis)** [opus, 얇은 층] — ①~④ 정박 위에서만 감사 리포트 작성. **제약**: 모든 문장이
stage 2~4의 grounding(엣지 id·내러티브 버전·시간 카운트·프록시)을 인용. **적대적 반대(ACH)**는 contested 엣지에
근거(프라이어 반박 금지). 없는 근거 창작 금지.

## 쓰기 (선택·격리) — 물질화 경로

기본은 read-only. 사용자가 "이 논지를 내 세계모델에 등재" 택하면:
- `POST /thesis/{id}/register` → 주장 인과를 `entity_relations`에 `epistemic_type=hypothesis`·`source_doc_id`(주입
  노트)·confidence≤0.5·`created_by=user` 태그로 **제안**(승인 큐, review_status='proposed'). K3 지식주입 +
  scenario `_persist_causal`(D-028) 선례 재사용.
- **독립성 불변식**: `created_by=user` 엣지는 `corroborated_by` 집계·falsifier refute 집계에서 **제외**. 네 주입이
  네 thesis를 확증하는 순환 구조적 차단.
- 승격(hypothesis→corroborated)은 오직 **독립·시간분산 증거** 축적 시, 그마저 사람 승인(consolidation D-050).

## IA / 화면

**월드모델 → 전망(미래-확률 축, D-073)** 아래 '논지 감사' — 질문 트래커와 형제(둘 다 미래-확률 1급 객체). 신규 페이지
최소화: 전망 서브탭에 편입 검토(`/thesis` 또는 질문 콘솔의 모드).

```
┌─ 논지 감사 ────────────────────────────────────┐
│  [thesis 붙여넣기 콘솔]                          │
│  ─────────────────────────────────────────────  │
│  주장 1: 컴퓨팅 = moat         🟢 일치           │
│    ↳ 엣지 OpenAI→컴퓨트 우위 conf0.70 · 2독립    │
│  주장 2: 순환출자 상환 의문     🟡 최근 급증       │
│    ↳ OpenAI 언급 2026-07 150건(6배) · negative엣지│
│  주장 3: 중국 = 부차           ⚪ 신규(그래프 없음)│
│  ─────────────────────────────────────────────  │
│  진자: AI 인프라 = 선반영 경고                    │
│  반증조건: ①하이퍼스케일러 CAPEX 가이던스 유지     │
│           ②OpenAI 자금조달 성사 → [프록시 감시]   │
│  [내 세계모델에 등재(가설로)] ← 선택·승인 게이트   │
└────────────────────────────────────────────────┘
```

- 각 주장 카드: 판정 배지(일치/충돌/신규/선반영) + **근거 링크**(엣지·내러티브·시간 → 1클릭 드릴다운, "왜?" §1).
- 최하단: 진자 위치 · 반증조건+프록시 · (선택) 등재 버튼.
- 컴포넌트: `shared/PageContainer` · 5-state · 근거는 EpistemicBadge/EntityChip 재사용.

## API

- `POST /api/spine/thesis/audit` (freeform text) → 델타 리포트(주장별 판정+근거·진자·반증·프록시). **read-only**, ~수 분(연쇄 LLM).
- `GET /api/spine/thesis/{id}` → 저장된 감사 결과(append-only 히스토리, 재조회 LLM 0).
- `POST /api/spine/thesis/{id}/register` → (선택) 격리 물질화 제안 → 승인 큐.

## 5-state (docs/policies/ui-states.md)

| 상태 | 처리 |
|---|---|
| Empty | thesis 미입력 — 콘솔 프롬프트 + 예시 |
| Loading | 분해+정박 진행(~수 분) — 스켈레톤 + 단계 표시 |
| **Partial** | 일부 주장만 정박(나머지 novel/코퍼스 얇음) → 얻은 것 표시 + **"코퍼스 얇음" 정직 배지**(프라이어로 안 메움) |
| Error | LLM 엔진 실패 → ErrorState + retry |
| Ideal | 전 주장 델타 + 진자 + 반증/프록시 + (선택) 등재 |

## 경계 (안 하는 것)

- **자동 등재 금지** — 기본 read-only. 쓰기는 명시적 선택 + 승인 게이트.
- **자기 교차검증 금지** — 사용자 주입 엣지는 corroborated_by에서 제외(독립성 불변식). 자기확증 차단.
- **사용자 프레임을 사실로 승격 금지** — 등재해도 hypothesis·conf≤0.5. 승격은 독립 증거+사람 승인만.
- **vocab-exact 매칭 의존 금지** — 의미검색으로 정박("순환출자" 정확어 2건이나 개념은 두툼 — 어휘가 아니라 의미로).
- **코퍼스 공백을 LLM으로 메우기 금지** — 없으면 novel로 정직히. "확인됨"인 척이 곧 ChatGPT 후퇴.
- **다중 에이전트 토론을 주 산출로 삼기 금지** — 토론은 ⑤의 얇은 층. 몸통은 ①~④ grounding.

## 재사용 (신규 지능 아님 — 배선)

이 기능은 새 지능이 아니라 기존 기계의 **오케스트레이션**: `decompose_question`(D-067) · `knowledge_state`(진자) ·
`falsifiers`(반증) · transcript 프록시(D-067) · `narrative_edge_evidence`(교차검증) · `resolve_and_enrich`(엔티티
해소) · scenario `_persist_causal`(격리 물질화 D-028) · RAG(인용 종합). 신규는 **감사 프레임(델타 출력) + read-only
정박 우선 규율**뿐.
