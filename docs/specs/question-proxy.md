# 핵심질문 ↔ 프록시 — 분할정복 질문 트래커

> 2026-07-26 기획. 배경: 리포트의 **핵심 질문**(D-049)이 지배 내러티브에서 도출되고, transcript 커넥터(D-061)가
> 그 관찰 **프록시**(하이퍼스케일러 CAPEX 등)를 실데이터로 채우기 시작했다. 그러나 지금은 두 조각이 끊겨 있다 —
> `proxy_registry.narrative_id`가 비어(프록시가 어느 질문에 매달렸는지 모름), 관측이 쌓여도 질문을 재판정하지 않는다.
> 이 스펙은 그 사이를 **분할정복(divide & conquer)** 구조로 잇는다: 핵심질문을 서브질문으로 쪼개고, 각 서브질문에
> 관측 프록시를 붙이고, 관측을 주기적으로 추적해 질문이 스스로 판정되게 한다. Q2(내러티브 앵커링)·Q6(사용자 질문
> 분해)·"프록시 고도화"(다양식화)·Q5(단일 소스 딥다이브)가 이 하나로 수렴한다.

## 관통 원칙 (비타협)

1. **질문 = 인식 사다리의 미결층** — 질문은 "아직 답 안 난 hypothesis, 단 프록시 기반 판정 메커니즘을 가진" 것.
   knowledge(검증 명제)의 미결 버전이다. 판정되면 지식으로 승격 → 기존 knowledge_state·falsifier·consolidation 재사용.
2. **능동 관측 설계 ≠ 수동 말뭉치 축적** — 지식은 말뭉치가 우연히 지지/반박을 쌓아 판정된다(수동). 질문은 **볼 것을
   미리 분할정복으로 지정하고 그 프록시만 추적**한다(능동). 이 차이가 Q5의 "누적 전 선제 상상" 한계를 뒤집는다.
3. **분할정복 2단** — 핵심질문 → 서브질문(논리적 분할, "이걸 보려면") → 프록시(관측 대상). 서브질문은 1:N 프록시.
   서브질문 층이 없으면 "전환되는가" 같은 복합 조건이 뭉개진다.
4. **프록시는 다양식(multi-modal)** — 수치 시계열만이 아니다. 수장 발언 태세·투자자 여론도 프록시다. 프록시 = 기존
   관측 스트림 위의 **typed adapter**("이 서브질문을 위해 어느 스트림을 어떻게 읽나").
5. **결합하되 융합하지 않음** — 질문 층은 독립 테이블. 서브질문을 인과 그래프 노드로 강제하지 않는다(어휘 파편화
   D-033 회피 + 태세·여론 수용). 단 numeric 프록시 관측은 `observations`로 엔티티에 투영, 질문은 `narrative_id`로
   내러티브(=인과 서브그래프)에 앵커 — 노드를 새로 뿌리지 않고 그래프 위에 얹힌다.
6. **비싼 노동은 사람 판단 뒤로 (D-020)** — 분해(LLM) 자체는 자동이되, 추적 활성화는 생성자별로(§생성자).

---

## 데이터 모델

기존 `proxy_registry`·`proxy_observations`(D-061)를 확장하고, 질문·서브질문 테이블을 신설한다.

```
questions(
  id, text,
  narrative_id,           -- 도출 출처 내러티브 (사용자 주입이면 NULL 또는 recall로 자동 결합)
  created_by,             -- 'system' (Q2 자동도출) | 'user' (Q6 주입)
  source_doc_id,          -- Q5: 단일 소스에서 출발한 경우 그 문서 (NULL 가능)
  status,                 -- proposed | tracking | resolved | dismissed
  lead_verdict,           -- 선행 판정 (fast: sentiment·stance 프록시 롤업) leaning_yes|no|mixed|unknown
  confirm_verdict,        -- 확정 판정 (slow: numeric 프록시 롤업) 〃 (D-068)
  divergence,             -- 선행↔확정 괴리 (quadrant_gap 질문 버전): aligned|lead_ahead|confirm_ahead
  verdict_summary,        -- 게으른 LLM 한 줄 종합 (하이브리드 판정의 서술부)
  conviction, salience,   -- knowledge_state 4상한 재사용 (판정 강도 × 시장 주목)
  created_at, updated_at
)

sub_questions(
  id, question_id,
  text,                   -- "하이퍼스케일러 CapEx 전망이 꺾이나/상향되나?"
  falsifier,              -- 반증조건: "이 방향으로 관측되면 핵심질문이 틀린 것" (falsifier 엔진 연동)
  verdict,                -- 서브질문 단위 판정 (프록시 관측 롤업)
  weight,                 -- 핵심질문 종합 시 가중 (기본 균등, 사람 조정 가능)
  created_at
)

proxy_registry(  -- 확장
  id, key, label,
  sub_question_id,        -- ★신설: 어느 서브질문에 매달렸나 (기존 narrative_id는 questions로 이동)
  modality,               -- ★신설: numeric | stance | sentiment
  tickers, unit, extract_hint,
  active, created_at
)

proxy_observations(  -- 확장
  id, proxy_id,
  source_type, source_id, -- ★신설: 범용 source_ref (기존 transcript_id 대체 — 다소스화)
  observed_at, value_num, value_text, direction, confidence, created_at
)
```

- **마이그레이션**: `proxy_observations.transcript_id` → `source_type='transcript', source_id=transcript_id`로 백필
  (기존 7건 보존). `proxy_registry.narrative_id`(현재 빈 컬럼)는 폐기하고 `sub_question_id`로 대체.
- **observations 투영**: modality='numeric' 프록시 관측은 `observations(entity_id, date, metric, value)`(현재 미가동)에도
  기록 → 엔티티 노드에 붙어 살아있는 모델·밸류에이션 입력으로 재사용. **이 기능이 observations 테이블을 처음 가동시킨다.**

---

## 생성자 2개 (Q2 자동도출 · Q6 사용자주입)

질문은 **하나의 객체, 두 생성자**. 다운스트림(분해→프록시→관측→판정)은 완전히 공유한다.

### ① 자동 도출 (Q2) — 제안 큐
- `report._narrative_power`가 지배 서사를 판별할 때 그 서사가 던지는 질문을 `questions`(created_by='system',
  status='proposed')로 emit + `narrative_id` 채움.
- LLM(sonnet)이 서브질문·프록시로 자동 분해하되 **status='proposed'로 대기** — 홈 승인 큐(agent_proposals 패턴)에
  올라가 사람이 승인해야 status='tracking'(추적·추출 시작). 매 내러티브마다 프록시가 늘어 추출 비용이 커지는 걸 막는다.

### ② 사용자 주입 (Q6) — 자동분해 + 편집
- "질문 콘솔"(지식 주입 콘솔 동형)에 질문 입력 → LLM 자동 분해(서브질문 A~E + 프록시 바인딩) → **사용자가 트리를
  편집**(서브질문 가지치기·추가, 프록시 티커/힌트 수정) → status='tracking' 즉시 시작. 사용자가 이미 의도를 표현했으니
  승인 큐 없이 편집으로 in-the-loop.
- **narrative_id 자동 결합**: 주입 질문이 기존 내러티브와 의미상 가까우면 `recall_for_query` 재사용으로 자동 앵커,
  없으면 NULL(자유부동).

### Q5 흡수 — 단일 소스 생성자
- 뉴스/아티클/유튜브 URL 한 건 → 그 문서를 `source_doc_id`로 하는 사용자 질문 생성(②의 특수 경우, corpus가 아니라
  단일 문서에서 출발). "SK하이퍼 뉴스 → SKT EPS·멀티플 리레이팅 재료인가?"가 질문이 되고 분할정복으로 추적.
  별도 기능이 아니라 생성자 ②의 소스가 단일 문서인 경우.

---

## 프록시 다양식 (modality)

| modality | 예시 서브질문 | 관측 소스 | 매핑되는 기존 기계 | 착수 |
|---|---|---|---|---|
| **numeric** | CapEx 추이·ARR·OPM·FCF·매출성장률 | 컨콜·재무·컨센서스 | `extract_proxies`(있음, 컨콜만) + 재무·컨센서스 추출기 | **1차** |
| **sentiment** | 투자자 여론이 식나 | 텔레/블로그/유튜브 | `signals` theme_surge·consensus_extreme·quadrant_gap 래핑 | 2차 (제일 쌈) |
| **stance** | 수장이 보수적으로 돌아서나 | person 발언 | person 감성 추적 (신규) | 3차 |

- 착수 순서: **수치(재무·컨센서스 추가) → 여론(signals 래핑) → 태세(신규)**. 무역(trade_stats) 프록시는 후속.
- `source_ref` 범용화가 다양식의 전제 — transcript 전용 FK를 (source_type, source_id)로 열어야 재무·컨센서스·신호가
  같은 관측 테이블에 들어온다.

---

## 판정 롤업 (하이브리드 + pace layer 2층, D-068)

프록시 관측 → 서브질문 판정 → 핵심질문 종합. **하이브리드**: 결정적 스코어(LLM 0) + 게으른 LLM 한 줄.

1. **프록시 → 서브질문 (결정적)**: 프록시 관측의 방향(up/down/flat) 카운트·최근성 가중 → 서브질문 verdict.
   **반증우선**: 서브질문의 `falsifier` 방향으로 꺾인 관측을 강조(예: E "OPM 축소"가 TRUE로 관측되면 굵게).
2. **서브질문 → 핵심질문, pace layer 2층 (결정적)**: 질문 안에 두 속도가 공존한다 — sentiment·stance(fast)는
   매일 움직이고 numeric(slow)은 분기마다만. 단일 점수로 뭉치면 fast 여론이 slow 실적을 압도해 verdict가
   출렁인다(온톨로지 §fact/hypothesis 안 섞기 위반). 그래서 프록시 **modality를 pace layer로 갈라 2층 롤업**:
   - **lead_verdict (선행, fast)** = sentiment·stance 프록시 관측 종합 → "여론·태세는 이미 X로 기울었다"(조기 경보).
   - **confirm_verdict (확정, slow)** = numeric 프록시 관측 종합 → "실적으로 확인된 방향"(후행).
   - **divergence** = 둘의 괴리를 신호로 — "여론은 식었는데 실적은 아직 강함"(lead_ahead) 등. `quadrant_gap`
     (주가×감성 괴리)의 **질문 버전**. 시차를 뭉개지 않고 정보로 만든다.
   어느 서브질문이 부정으로 돌아섰나가 각 층 종합의 핵심 신호(단순 다수결 아님, 반증 가중).
3. **게으른 LLM 종합 (서술)**: 두 verdict·divergence가 바뀔 때만 haiku 한 줄로 `verdict_summary` 갱신 —
   "투입·수요(A·B)는 확정 확인, 단 여론(D)은 선행으로 식기 시작, 전환(C·E) 프록시는 아직 공백" 류. 캐시.

## 판정 주기 (Tracking 트리거, D-068)

"주기적 추적"은 별개 두 타이밍이다 — **관측 추출**과 **판정 롤업**을 갈라서 본다. 둘 다 event-driven(소스/관측
갱신 편승), **고정 폴러·cron 재판정 금지**.

- **관측 추출 = 소스별 event-driven, 기존 이벤트에 편승** (프록시마다 pace layer가 다르므로):
  - numeric ← 컨콜 수집 후(`extract_proxies` 기존 패턴)·재무 갱신·컨센서스 일별 스냅샷 (느림, 분기)
  - sentiment ← 30분 cron(signals 계산에 편승) (빠름, 연속)
  - stance ← 새 발언 문서 enrich 후 (불규칙)
  → 새 스케줄러를 만들지 않는다. Phase 1은 numeric뿐이라 "컨콜/재무 수집 후 훅" 하나로 충분.
- **판정 롤업 = 관측 갱신에 편승, 재료 없으면 no-op** (D-059 내러티브 재생성·digests doc_ids_hash 가드와 동형):
  결정적 스코어는 관측 하나 들어올 때마다 재계산(쌈), LLM 서술(`verdict_summary`)만 판정이 실제 바뀔 때 게으르게.

---

## 그래프 결합 (결합하되 융합 안 함, D-033 파편화 회피)

- 질문/서브질문/프록시는 **독립 테이블** — 인과 노드를 새로 안 뿌린다.
- **접점 (a)**: numeric 프록시 관측 → `observations`(entity_id·metric·value) 투영 → 엔티티 노드에 붙음. 잠자던 테이블 가동.
- **접점 (b)**: 질문은 `narrative_id`로 내러티브(=인과 서브그래프)에 앵커 → 질문↔그래프 링크는 내러티브 경유로 존재.
- 서브질문 A→B→E가 인과 체인(투입→수요→전환→마진)과 겹치더라도 노드로 강제 편입하지 않음 — 태세(C)·여론(D)처럼
  노드 아닌 관측을 수용하기 위함.

---

## IA (화면)

- **월드모델 > 지식 탭에 "미결 질문" 층 신설** — 질문 트리(핵심질문 → 서브질문 → 프록시 현황 + verdict 배지). 지식과
  판정 메커니즘이 달라 완전 융합이 아니라 지식 뷰 안에서 인접 배치(질문=미결, 지식=검증).
- **질문 콘솔** — 지식 주입 콘솔 동형(질문 입력 → 자동분해 → 트리 편집).
- **내러티브 상세 미러링** — "이 서사의 핵심질문 + 서브질문 현황"을 내러티브 페이지에 얹어, 서사가 딛고 선 미결 질문을 노출.
- **홈 승인 큐** — 자동 도출 질문(Q2)의 proposed 트리가 헤더 인박스에 다른 제안들과 함께.

## 5-state
- **Empty**: 추적 중 질문 없음 → "핵심질문을 주입하거나, 내러티브에서 자동 도출되길 기다리세요" + 질문 콘솔 CTA.
- **Loading**: 분해(LLM) 중 스켈레톤 / 관측 추출 중 프록시별 스피너.
- **Partial**: 서브질문은 있으나 일부 프록시 관측이 아직 없음 → "미판정" 배지 + 빈 프록시 명시(질문의 어느 부분이 안 덮였나).
- **Error**: 분해·추출 실패 → ErrorState + job_runs 노출(D-062 silent-0 교훈).
- **Ideal**: 핵심질문 트리 + 서브질문 verdict + 프록시 관측 시계열 + 종합 판정 헤드라인 + 반증 꺾임 강조.

---

## Phase 스코프 (D-004 — 렌즈 1개 end-to-end 먼저)

세상 모든 질문을 day1에 모델링하지 않는다. **AI capex 질문 하나로 루프를 증명한 뒤 확장**한다.

> "폭발적 AI 사용량이 막대한 capex를 감당할 매출·마진으로 전환되는가?"
> → 서브질문 A(CapEx)·B(ARR)·C(수장 태세)·D(여론)·E(OPM/FCF) → 프록시 → 관측 → 판정.
> 지금 시드 프록시 2개(hyperscaler_capex·dc_demand_backlog)는 **투입·수요 절반만** 덮고, 정작 질문의 핵심인
> "전환"(매출·마진 = C·E)은 프록시가 없다 — 이 공백을 채우는 게 "프록시 고도화"의 실제 내용.

- **Phase 1**: 데이터 모델(questions·sub_questions + proxy 확장) + 사용자 주입 생성자(②) + numeric 프록시(재무·컨센서스
  추출기) + 결정적 판정 + 지식 탭 미결 질문 뷰. AI capex 질문으로 end-to-end 검증.
- **Phase 2**: 자동 도출 생성자(①, 제안 큐) + sentiment·stance 프록시 + observations 투영 + 내러티브 미러링.
- **Phase 3**: 판정 → 지식 승격 고리 + Q5 단일 소스 생성자 + Tracking 주기(이벤트 트리거) 정교화.

## Q5 — 단일 소스 딥다이브 (설계, 2026-07-26 확정)

**문제**: 신호가 mention 임계 기반이라 "한 번 언급됐지만 상상을 자극하는" 소스(SK하이퍼 뉴스·젠슨황 인터뷰)를
못 잡는다(corpus 최신편향). Q5는 사용자가 "이 소스 하나가 중요하다, 파보자"를 누적 없이 선언하게 한다.

**핵심 차이 (② 와)**: ②는 사용자가 *질문*을 준다. Q5는 사용자가 *소스*를 준다 → **소스→핵심질문 도출**이라는
새 단계가 앞에 붙고, 그 뒤 분해는 ②를 100% 재사용한다.

```
기존 수집 문서(/doc/:id, 피드)
   │  ★신규: derive_questions_from_doc(doc_id) — sonnet이 소스를 읽고
   │         "딥다이브할 핵심질문 1~3개"(+파급 사건 event 문구) 도출
   ▼
핵심질문 후보 → 사용자 픽/편집
   ├─(a) decompose_question(text, source_doc_id=doc_id) — 질문 트래커 (기존 ② 재사용)
   └─(b) build_scenario(event) — 파급 시나리오도 함께(scenarios 캐시)
```

**확정 결정 (2026-07-26)**:
- **입력 = 기존 수집 문서만**(MVP). 외부 URL 붙여넣기(유튜브 단건 커넥터·뉴스 범용 fetch)는 후속.
- **소스→질문 = 시스템 자동 도출**(sonnet) → 사용자 픽/편집. "선제적 상상 보조"의 핵심 가치.
- **시나리오도 함께**: 같은 소스에서 도출한 event로 `build_scenario`(pipeline/scenario.py)도 태워 파급 체인 생성.
  질문 트래커(무엇을 볼지)와 시나리오(무슨 일이 벌어질지)가 한 소스의 두 렌즈.
- `source_doc_id`로 출처 추적 + recall_for_query로 가까운 내러티브에 narrative_id 자동 연결.

**구현 요소**: `derive_questions_from_doc(doc_id)`(신규, sonnet — 질문 후보 + event) · POST `/api/spine/questions/from-doc`
(도출→후보 반환) · 기존 `decompose_question`·`build_scenario` 재사용 · FE: `/doc/:id`·피드에 "이 소스로 파보기" 버튼
→ 후보 픽 모달 → 질문 트래커 + 시나리오 진입.

## 프록시 보드 (D-240)

프록시를 '질문의 서브질문에 매단 LLM 추출값'에서 **주제·논지를 지켜보는 지표 묶음(보드)**으로 넓힌다. 보드 = 이름 +
지표 목록 + (선택) 연결된 핵심질문·서사·종목 묶음. 사용자가 필요할 때 직접 만들고, 만들 때 한 번 지표 정의를 제안받는다.
보드 값은 판정 엔진(`refresh_questions`)과 무관하게 원천이 갱신되는 대로 산다. 판정 엔진은 이 값들을 입력으로 쓰는 상위 층으로 남는다.

### 데이터 모델

- `proxy_registry` 확장: `adapter`(어댑터 kind, NULL=기존 질문 프록시)·`adapter_ref`(`kind:body`)·`warn_direction`(up|down|NULL — 어느 방향이 '주의'인가)·`rationale`(왜 이 주제의 신호인가).
- `proxy_boards(id, name UNIQUE, description, question_id?, narrative_id?, group_id?, created_at, updated_at)`
- `proxy_board_items(board_id, proxy_id, position, PK(board_id, proxy_id))`
- **결정적 어댑터의 값은 `proxy_observations`에 쓰지 않는다.** 원천 테이블을 요청 시 읽는다(중복 저장·갱신 시점 어긋남 회피).
- 보드에서 새로 정의한 지표는 보드 소유 행(`adapter` NOT NULL, `sub_question_id` NULL)이다. 어느 보드에도 없게 되면 지운다.
  기존 질문 프록시(`adapter` NULL)는 보드에서 빼도 남는다. 기존 프록시를 이름·주의 방향을 붙여 담고 싶으면
  `transcript:<id>`·`corpus:<id>` 정의로 보드 소유 행을 만든다(원 프록시를 덮어쓰지 않음).

### 어댑터 (`pipeline/proxy_adapters.py`, LLM 0·네트워크 0)

| kind | ref 형식 | 값 | 원천 · 재사용 계산 | 변화 기준 |
|---|---|---|---|---|
| credit | `credit:<티커>` · `credit:group:<묶음키>` | 회사채 스프레드(bp). 묶음은 구성사 평균(거래 없는 날은 최대 10일 이어 씀, 구성사 전원 값이 있는 날만) | `credit_quotes`·`credit_bonds`·`treasury_curve` · `credit_spreads.spread_series` | 30일 전 |
| trade | `trade:<HS>[:import][:mom\|yoy\|yoy3m\|z]` | 월 수출액(USD), 접미사면 증가율(%)·YoY z | `trade_stats`·`trade_follow` · `trade_metrics.derive` | 전월 |
| call_momentum | `call_momentum:<집계키>` · `call_momentum:<티커>` | 실적 시즌별 기업 수(집계) / 발표별 모멘텀 점수(티커, 첫 발표 제외) | `call_momentum.reasons`(판정 뒤 동인·가이던스) · `call_momentum.season` | 집계: 직전 시즌의 같은 경과 시점 / 티커: 직전 발표 |
| indicator | `indicator:<market_indicators 키>` · `indicator:risk_curve` | 지표 값. `risk_*`는 정본 정제(`risk.clean_rows`)와 bp 환산, `risk_curve`=(10Y−2Y)×100bp | `market_indicators` | 30일 전 |
| retail | `retail:<지표키>[_pct]` | 20일 파생지표, `_pct`는 5년 백분위 | `retail_flows` · `retail_heat.computed` | 30일 전 |
| sector | `sector:<대분류>[:rs_long]` | 단기 RS(1M, 기본)·장기 RS(12M) 백분위 | `sector_map`·`stock_prices` · `sector_rs.compute_sector_map`(현재 + 1·2·3주 전 궤적, 15분 캐시) | 3주 전 |
| price | `price:<종목코드>` | 종가(원) | `stock_prices` | 30일 전 |
| transcript | `transcript:<proxy_id>` | 기존 컨콜 추출 수치(태세는 방향 +1/0/−1) | `proxy_observations` | 직전 관측 |
| corpus | `corpus:<proxy_id>` | 기존 문서 여론 방향 +1/0/−1 | `proxy_observations` | 직전 관측 |

컨콜 모멘텀 집계키: `guidance_raised_count`(성장 지표 가이던스 상향) · `capex_raised_count`(CAPEX 가이던스 상향) ·
`new_driver_count`(새 성장 동인) · `ai_driver_count`(AI 관련 동인 new·accelerating) · `candidate_count`(모멘텀 후보).
진행 중인 시즌을 직전 시즌 전체와 비교하면 시즌 초마다 급감으로 보이므로, 직전 시즌도 같은 경과 일수까지만 센다.
`indicator` 카탈로그는 `risk_sync_*`(수집 기록)와 정본이 따로 있는 레거시 계열(`vix`·`fear_greed`·`macro_us2y`·`macro_us10y`)을 뺀다.

어댑터 계약: `catalog(conn, q, limit)` → `[{ref, label, unit}]`(값이 있는 것만) · `describe(conn, ref)` → 원천에 없으면 None ·
`series(conn, ref, since)` → `[(date, value)]` · `latest` → `{value, as_of, change, change_pct, change_basis, direction, unit}`.
**`as_of`는 원천 날짜다(지금 시각이 아니다).** 수출입은 `YYYY-MM`. `change`는 값과 같은 단위의 차이, `change_pct`는 수준 지표
(가격·수출액)에만 붙는다. `in_warn` = `warn_direction`이 있고 `direction`과 같을 때.

### API (`routers/proxy_boards.py`, prefix `/api/spine/proxy-boards`)

| 메서드 | 경로 | 내용 | LLM |
|---|---|---|---|
| GET | `/` | 보드 목록 + `item_count` + `in_warn_count`(주의 방향으로 움직인 지표 수) | 0 |
| POST | `/` | 생성 `{name, description?, question_id?, narrative_id?, group_id?}` · 이름 중복 409 | 0 |
| GET | `/{id}?days=` | 상세 — 항목별 label·adapter·adapter_ref·unit·latest·warn_direction·in_warn·series. `days` 없으면 어댑터 기본 길이(일간 3개월, 수출입 13개월, 컨콜 2년, 섹터 궤적) | 0 |
| PATCH | `/{id}` | 이름·설명·연결 수정 | 0 |
| DELETE | `/{id}` | 보드와 항목 삭제(보드 소유 지표 정리) | 0 |
| POST | `/{id}/items` | `{proxy_id}` 또는 `{label, adapter, adapter_ref, unit?, warn_direction?, rationale?}`. 모르는 어댑터·원천에 없는 ref·없는 프록시·둘 다 보냄 → 422, 중복 → 409 | 0 |
| DELETE | `/{id}/items/{proxy_id}` | 항목 빼기 | 0 |
| PUT | `/{id}/items/order` | `{proxy_ids}` — 현재 항목 전체의 순열이 아니면 422 | 0 |
| GET | `/adapters` · `/adapters/{kind}/catalog?q=` | 항목 추가 UI용 어댑터 목록·카탈로그 | 0 |
| POST | `/suggest` | `{topic, question_id?, narrative_id?}` → 지표 후보 제안 | sonnet 1회 |

### 지표 제안 (`pipeline/proxy_boards.suggest`)

보드를 만들 때만 POST로 부른다. GET 경로에서는 부르지 않는다.

1. 주제(+연결된 질문·서사 문장)에서 키워드를 뽑아 어댑터별 카탈로그 요약을 만든다 — 어댑터별 기본 상위 몇 개 + 키워드에 걸린 참조.
   실제 데이터가 있는 참조만 들어간다.
2. sonnet 1회(`enrich._call_claude_code`, `llm_calls` 원장에 `proxy_boards`로 기록). 출력은 JSON 배열
   `[{label, adapter, adapter_ref, unit, warn_direction, rationale, lead_or_confirm, needed}]`. 원천이 없으면 adapter·adapter_ref를 null로 두고 `needed`에 필요한 데이터를 적게 한다.
3. 모든 후보를 카탈로그로 다시 검증한다. 통과 → `candidates`(단위는 원천 기준으로 덮어씀, 최대 10개).
   adapter 없음·모르는 어댑터·원천에 없는 ref·값 없음 → `needs_source`에 사유와 함께. 조용히 버리지 않고, 지어낸 ref는 받지 않는다.
4. LLM을 쓸 수 없으면 503, 응답을 읽지 못하면 502.

사용자가 고르고 고친 후보만 `POST /{id}/items`로 보드에 들어간다.

### 5-state (보드 상세)

- **Empty**: 보드에 지표 없음 → 카탈로그에서 추가 또는 제안 받기.
- **Loading**: 상세 첫 요청은 섹터 RS 계산 때문에 수 초 걸릴 수 있다(이후 15분 캐시).
- **Partial**: 일부 항목의 `latest.value`가 null이거나 `change`가 null(기준점 이전 이력 부족) → 항목별로 '값 없음'·'변화 기준 없음'.
  `missing: true` 항목은 프록시가 지워진 것(질문 삭제 등).
- **Error**: 상세 요청 실패 → ErrorState.
- **Ideal**: 항목별 최신값·원천 날짜·변화(기준 표기)·주의 배지·스파크라인.

## 미해결 / 후속 (Phase 밖)

- ~~판정 주기(Tracking) 트리거~~ — **해소(D-068)**: 관측 추출·판정 롤업 모두 event-driven 편승, 재료 없으면 no-op.
- **서브질문 승격 기준** — 질문 verdict가 얼마나 확고해야 지식으로 승격하나(conviction 임계).
- **프록시 관측 독립성** — 말뭉치 복제편향(보도자료 1→기사 10)이 sentiment 프록시 방향을 부풀릴 위험(D-065 한계 5와 동일).
- **stance 프록시 데이터** — 수장 발언 태세 변화 추적은 person 감성 시계열이 선결(현재 감성 태깅은 있으나 프록시화 안 됨).
