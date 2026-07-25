## 결론부터

Explorer의 **As-is 방향은 맞다.** 이미 단순 지식그래프가 아니라 사실·가설 구분, 시간·지역 정박, 출처 추적, 내러티브 버전, 반증 조건, 피드백 루프, 사람 승인까지 갖춘 인과 월드모델이다.

내가 본 핵심 문제는 기능 부족이 아니다.

> **그래프에 저장된** `confidence`**가 서로 다른 의미를 너무 많이 맡고 있고, 그 값을 곱한 결과가 사실상 multi-hop reasoning의 대표 점수로 사용된다는 점**이다.

현재 구조에서는 “가장 믿을 만한 경로”와 “가장 영향이 큰 경로”, “지금 이 종목에 가장 잘 적용되는 경로”가 섞일 수 있다. 따라서 전체를 재설계하기보다는 다음과 같이 바꾸는 것이 적절하다.

> **저장 단계에서는 인과 주장·근거·범위를 분리하고, 질의 단계에서는 대상과 문맥에 대한 적용 가능성을 계산하며, 결과는 하나의 점수가 아니라 여러 축의 reasoning trace로 보여준다.**

---

# 1. Explorer의 As-is

## 1-1. 제품 철학

Explorer는 다음 시스템이다.

```text
문서와 관측을 수집한다
→ 엔티티와 인과관계를 추출한다
→ 사실·관측·가설을 구분한다
→ 출처·시간·지역을 붙인다
→ 반복 근거와 반증을 축적한다
→ 내러티브와 시나리오로 해석한다
→ 사람이 최종 판단한다

```

즉, “정답을 계산하는 모델”이 아니라 **출처 달린 인과 가설을 축적하고 검토하는 시스템**이다.

현재 `entity_relations`에는 이미 다음 정보가 들어간다.

- `epistemic_type`
- `confidence`
- `mechanism`
- `reference_period`
- `time_orientation`
- `geo_scope`
- `valid_from/to`
- `narrative_id`
- `feedback_note`
- `promoted_knowledge_id`

또한 내러티브에서 생성된 인과 엣지를 전역 그래프에 물질화하고, 독립 내러티브 반복을 교차검증 근거로 축적하며, 일정 기준 이상이면 지식 승격 후보로 보낸다. 시나리오에서 생성된 가정적 인과관계는 `confidence` 상한을 낮추는 방식으로 보수적으로 다룬다.

이 구조 자체는 상당히 일관적이다.

## 1-2. 현재 multi-hop 방식

현재 `narrative_[graph.py](http://graph.py)`는 대략 다음 방식으로 작동한다.

```text
내러티브 노드에서 출발
→ 상류는 CAUSES를 따라 근본 원인 탐색
→ 하류는 CAUSES와 BENEFITS_FROM을 따라 수혜 대상 탐색
→ 각 경로의 confidence를 곱함
→ 상위 경로를 반환

```

피드백 루프는 동일 엣지를 무한 반복하지 않도록 엣지 ID 기반 방문 집합과 깊이 제한으로 관리하고, `regime`·`structure` 같은 느린 층에서 근본 원인 순회를 정지한다.

따라서 As-is는 다음과 같이 요약할 수 있다.

```text
그래프 저장:
출처·시간·지역·인식론이 붙은 인과 주장

경로 탐색:
confidence 중심의 multi-hop propagation

최종 해석:
LLM이 경로와 문서를 종합해 내러티브·시나리오·수혜주 제시

```

---

# 2. 내가 본 한계

## 한계 1. `confidence`가 너무 많은 의미를 맡는다

현재 설계 철학에는 다음 표현이 있다.

> confidence = 엣지 가중치 — 인과의 강도·확실성을 0~1로.

하지만 다음은 서로 다른 개념이다.

```text
주장이 참이라는 확신
관계가 성립할 경우 효과가 큰 정도
현재 시점에서 작동하는 정도
특정 기업이 그 요인에 노출된 정도
근거가 반복적으로 등장한 정도

```

이를 하나의 `confidence`에 담으면 해석이 불가능해진다.

예를 들어 두 엣지가 모두 `0.7`일 수 있다.

```text
A. 효과는 약하지만 거의 확실한 관계
B. 효과는 매우 크지만 아직 불확실한 관계

```

경로 탐색에서는 동일한 0.7로 취급되지만 투자 판단의 의미는 완전히 다르다.

### 결과적으로 생기는 문제

- 강한 효과와 높은 확신을 구분하지 못한다.
- 반복 언급이 인과 강도처럼 보일 수 있다.
- 가장 믿을 만한 경로가 가장 중요한 경로처럼 선택된다.
- UI에서 `confidence 0.8`이 무엇을 뜻하는지 설명하기 어렵다.
- 시간이 지나면서 값의 의미가 변질될 수 있다.

---

## 한계 2. confidence 곱은 “진실 가능성”도 “시장 영향”도 아니다

현재 경로 랭킹은 confidence 곱을 사용한다.

```text
0.9 × 0.8 × 0.7 = 0.504

```

이 계산은 **긴 경로를 보수적으로 평가하는 휴리스틱**으로는 타당하다. 하지만 그 결과가 무엇인지 명확하지 않다.

이 값은 다음 중 어느 것도 직접 의미하지 않는다.

- 이 시나리오가 발생할 확률 50.4%
- 종목 이익이 50.4% 증가
- 주가 상승 가능성 50.4%
- 이 경로가 다른 경로보다 50.4% 중요

그런데 시스템이 top-3 경로를 반환하면 사용자는 자연스럽게 이를 “중요한 인과 경로 순위”로 받아들인다.

실제로는:

> **출발부터 도착까지 비교적 높은 confidence 엣지들로 구성된 경로**

에 가깝다.

즉, 현재 경로 점수는 **epistemic reliability ranking**이지 **causal impact ranking**이 아니다.

---

## 한계 3. `geo_scope`와 `reference_period`가 저장되지만 reasoning에 충분히 사용되지 않는다

Explorer는 이미 인과 주장에 장소와 시간을 저장한다.

```text
geo_scope
reference_period
time_orientation
valid_from/to

```

이는 좋은 설계다. 문제는 저장된 scope와 실제 질문의 문맥을 대조하는 명시적 단계가 약하다는 점이다.

예를 들어:

```text
미국 주택담보대출 금리 상승
→ 미국 주택 수요 감소

```

이 엣지가 사실에 가깝더라도 한국 건설사 분석에 바로 적용되는 것은 아니다.

확인해야 할 것은:

```text
해당 회사가 미국 주택시장에 노출되어 있는가?
직접 매출인가, 공급망 간접 노출인가?
현재 질문의 시점이 엣지의 reference period에 포함되는가?
전달 메커니즘이 아직 유효한가?

```

현재는 이 판단을 주로 시나리오 LLM이나 최종 리포트가 암묵적으로 수행한다. 따라서 그래프 순회 자체는 scope가 맞지 않는 경로도 후보로 반환할 수 있다.

---

## 한계 4. `CAUSES`와 `BENEFITS_FROM`이 같은 경로 계산에 섞인다

두 관계는 본질적으로 다르다.

```text
AI 서버 출하 증가
CAUSES
HBM 수요 증가

```

이는 변수 간 인과 주장이다.

```text
SK하이닉스
BENEFITS_FROM
HBM 가격 상승

```

이는 기업의 노출과 가치 포착에 대한 투자 가설이다.

`CAUSES`는 원인에서 결과로 흐르지만, `BENEFITS_FROM`은 보통 회사와 외부 요인의 관계를 압축한 것이다. 여기에는 이미 여러 숨은 전제가 들어 있다.

```text
회사가 해당 제품을 실제 판매한다
가격 상승분이 매출에 반영된다
원가가 동시에 더 오르지 않는다
물량 감소가 가격 상승을 상쇄하지 않는다
영업이익 증가가 EPS로 이어진다
시장에 이미 반영되지 않았다

```

따라서 `BENEFITS_FROM`을 `CAUSES`와 동일한 계산 단위로 사용하면, 경로 중간의 논리를 건너뛰게 된다.

---

## 한계 5. 재적재·반복 확인과 독립 근거가 완전히 같지는 않다

현재 시스템은 재적재 시 confidence를 강화하고, 여러 내러티브가 같은 엣지를 주장하면 `corroborated_by`를 누적한다.

하지만 문서나 내러티브가 여러 개라는 사실이 독립 근거가 여러 개라는 뜻은 아니다.

```text
기업 보도자료 1개
→ 기사 10개가 재인용
→ 블로그 20개가 기사 해설
→ 내러티브 여러 개에서 반복 등장

```

실질적 근거는 하나일 수 있다.

따라서 다음은 분리해야 한다.

```text
문서 반복 횟수
독립 원천 수
원천 유형 다양성
서로 다른 시점의 반복 관측
직접 관측과 해석의 구분
지지 근거와 반박 근거

```

그렇지 않으면 “많이 회자된 가설”이 “강하게 검증된 가설”로 승격될 위험이 있다.

---

## 한계 6. 인과 주장과 현재 상태가 섞일 가능성이 있다

다음 두 문장은 다르다.

```text
금리 상승은 주택 수요를 감소시키는 경향이 있다.
현재 미국 주택담보대출 금리는 상승 중이다.

```

첫 번째는 **인과 주장**이고, 두 번째는 **현재 상태 또는 관측**이다.

Explorer에는 `observations`, `models`, `proxy_observations`, 무역통계, 컨센서스 시계열 등의 구조가 있지만, 핵심 그래프 reasoning은 아직 정적 인과 주장에 더 가깝다.

따라서 “이 경로가 논리적으로 존재한다”와 “현재 그 경로가 활성화돼 있다”가 구분되지 않을 수 있다.

---

## 한계 7. reasoning 결과의 감사 가능성이 부족하다

현재 결과에는 인과 체인과 근거가 나타나지만, 시스템 내부 판단을 다음처럼 분해해 보여주는 계약은 아직 명확하지 않다.

```text
왜 이 경로를 선택했는가?
어떤 엣지가 가장 취약한가?
어느 지역·시점 조건이 맞았는가?
어떤 기업 노출을 전제로 했는가?
효과는 강하지만 불확실한가?
효과는 작지만 확실한가?
어떤 사실이 나오면 이 경로가 무효화되는가?

```

Explorer의 철학은 “결론보다 출처 달린 가설 추적”인데, 경로 점수가 하나이면 오히려 그 철학을 약화시킨다.

---

# 3. 제안하는 To-be

## 3-1. 전체 구조

To-be는 그래프를 버리는 것이 아니다. 현재 그래프를 네 층으로 명확히 나누는 것이다.

```text
① Causal Claim Layer
무슨 원인이 무엇에 어떤 방향으로 작용하는가

② Evidence Layer
왜 이 주장을 믿는가, 누가 지지·반박하는가

③ Context & Exposure Layer
현재 언제·어디서 작동하며 대상이 얼마나 노출돼 있는가

④ Reasoning Run Layer
특정 질문에서 어떤 경로를 선택했고 어떻게 평가했는가

```

---

## 3-2. Layer 1 — 인과 주장 자체

현재 `entity_relations`를 유지하되 엣지의 의미를 명확히 분해한다.

### 현재

```json
{
  "relation_type": "CAUSES",
  "confidence": 0.78,
  "geo_scope": "글로벌",
  "reference_period": "2026-2028",
  "mechanism": "..."
}

```

### 제안

```json
{
  "relation_type": "CAUSES",
  "epistemic_type": "hypothesis",

  "effect_direction": "positive",
  "effect_strength": "strong",
  "confidence": 0.78,

  "geo_scope": ["글로벌"],
  "reference_period": "2026-2028",
  "lag_min_days": 90,
  "lag_max_days": 540,

  "conditions": [
    "AI 가속기 출하 증가",
    "서버당 HBM 탑재량 유지 또는 증가"
  ],

  "mechanism": "AI 서버 수와 서버당 HBM 탑재량 증가"
}

```

### 각 값의 의미


| 필드                 | 질문                      |
| ------------------ | ----------------------- |
| `confidence`       | 이 인과 주장을 얼마나 믿는가?       |
| `effect_direction` | 원인이 결과를 증가시키는가, 감소시키는가? |
| `effect_strength`  | 관계가 성립할 경우 효과는 얼마나 큰가?  |
| `geo_scope`        | 이 주장은 어디에서 작동하는가?       |
| `reference_period` | 언제 작동하는 주장인가?           |
| `lag`              | 원인 이후 결과까지 얼마나 걸리는가?    |
| `conditions`       | 어떤 전제가 있어야 성립하는가?       |
| `mechanism`        | 왜 그런 결과가 발생하는가?         |


### `effect_strength`는 숫자보다 범주형으로 시작

Explorer는 거짓 정밀을 금지하므로 처음부터 `0.73` 같은 값을 생성하게 하는 것은 권하지 않는다.

```text
unknown
weak
moderate
strong
dominant

```

내부 랭킹이 필요할 때만 임시 매핑한다.

```text
weak       0.25
moderate   0.50
strong     0.75
dominant   1.00

```

이 수치는 실제 효과 추정값이 아니라 상대적 탐색 휴리스틱이다.

---

## 3-3. Layer 2 — 근거를 엣지에서 분리

`confidence`를 재적재할 때 직접 강화하는 방식보다, 근거 원장을 별도로 두고 confidence를 계산하거나 갱신하는 편이 낫다.

### 제안 테이블

```text
relation_evidence

```

예시:

```json
{
  "relation_id": 123,
  "source_doc_id": 918,
  "stance": "support",
  "evidence_type": "company_guidance",
  "source_family": "SK하이닉스 2Q 컨콜",
  "observed_at": "2026-07-23",
  "independence_group": "skhynix_2026q2_call",
  "directness": "primary",
  "excerpt_or_claim": "...",
  "extraction_confidence": 0.91
}

```

### 이 구조가 필요한 이유

`confidence`를 다음 요소의 결과로 만들 수 있다.

```text
초기 epistemic confidence
+ 독립 원천의 지지
+ 서로 다른 시점의 반복 관측
+ 1차 자료 비중
+ 출처 유형의 다양성
- 반박 근거
- 오래된 근거의 감쇠

```

중요한 점은:

> confidence를 영구적인 수동 점수로만 보지 않고, 근거 원장으로부터 설명 가능한 상태로 만든다.

단, 완전히 자동 계산할 필요는 없다. 사람이 승인한 confidence와 기계 제안값을 분리해도 된다.

```text
model_confidence
reviewed_confidence

```

---

## 3-4. Layer 3 — scope와 applicability 분리

`geo_scope`, `reference_period`, `conditions`는 엣지에 계속 저장한다. 이것들은 인과 주장의 고유 정보다.

반면 `applicability`는 저장하지 않는다.

```text
applicability(edge, target, query_context, as_of)

```

질의 시 계산한다.

### 구성요소

```text
geo_match
temporal_match
condition_match
target_exposure
mechanism_match
state_activation

```

예:

```json
{
  "edge_id": 123,
  "target_entity_id": 456,
  "as_of": "2026-07-24",

  "geo_match": "high",
  "temporal_match": "high",
  "condition_match": "partial",
  "target_exposure": "high",
  "state_activation": "observed",

  "applicability": "medium_high",

  "reasons": [
    "매출의 상당 부분이 미국 AI 데이터센터 투자와 연결됨",
    "다만 신규 CAPEX가 실제 장비 발주로 전환되는 시차가 존재함"
  ]
}

```

이 결과는 `entity_relations`에 넣지 않고 reasoning 결과나 시나리오 캐시에 둔다.

### 핵심 구분

```text
geo_scope
이 관계가 어디에서 작동하는가

geo exposure
대상이 어느 지역에 얼마나 노출되어 있는가

geo match
둘이 얼마나 겹치는가

applicability
geo를 포함한 전체 문맥 적합도

```

따라서 geo 정보와 applicability는 중복되지 않는다.

---

## 3-5. 기업 노출 관계를 별도로 모델링

수혜주 reasoning을 개선하려면 `BENEFITS_FROM`을 최종 결론과 기초 노출 관계로 구분하는 것이 좋다.

### 현재 압축 표현

```text
SK하이닉스
BENEFITS_FROM
HBM 가격 상승

```

### 더 명시적인 표현

```text
SK하이닉스
EXPOSED_TO
HBM 가격

HBM 가격 상승
CAUSES
SK하이닉스 평균판매가격 상승

평균판매가격 상승
CAUSES
매출총이익 증가

매출총이익 증가
SUPPORTS
Forward EPS 상승

```

여기서 `BENEFITS_FROM`은 다음 두 방식 중 하나로 둔다.

### 방안 A — 최종 요약 엣지

상세 경로에서 파생한 presentation shortcut으로 둔다.

```text
BENEFITS_FROM = derived relation

```

### 방안 B — 투자 가설 엣지

인간이나 LLM이 만든 압축 가설로 유지하되 `hypothesis`로 명확하게 표시하고, 상세 근거 경로를 연결한다.

```json
{
  "relation_type": "BENEFITS_FROM",
  "derived_from_path_id": 789,
  "epistemic_type": "hypothesis"
}

```

나는 **B로 시작하고 장기적으로 A로 이동**하는 방식을 추천한다. 처음부터 모든 기업 재무 전달 경로를 세분화하면 구축 비용이 너무 크다.

---

## 3-6. Path score를 하나가 아닌 벡터로 바꾸기

현재:

```text
path_score = confidence의 곱

```

제안:

```text
path_assessment = {
  belief,
  impact,
  applicability,
  activation,
  fragility
}

```

### ① Belief

경로 전체를 얼마나 믿을 수 있는가.

```text
belief = 가장 약한 엣지 또는 보정된 기하평균

```

곱셈은 긴 경로를 너무 강하게 벌할 수 있으므로 기본값은 다음 중 하나가 좋다.

```text
min(edge confidence)

```

또는

```text
geometric_mean(edge confidence) × hop_penalty

```

### ② Impact

관계가 성립할 경우 결과가 얼마나 중요한가.

```text
effect_strength의 결합

```

다만 impact는 곱셈만으로 처리하기 어렵다. 공급망 병목처럼 한 단계가 지배하거나, 영업 레버리지로 뒤 단계에서 증폭될 수 있기 때문이다.

초기에는:

```text
low / medium / high

```

정도로 충분하다.

### ③ Applicability

현재 대상과 문맥에 얼마나 부합하는가.

```text
scope + exposure + conditions

```

### ④ Activation

현재 원인이 실제로 활성화되어 있는가.

```text
inactive
emerging
observed
accelerating
reversing
unknown

```

이는 `observations`, 컨콜 프록시, 무역통계, 가격, 컨센서스 등을 사용한다.

### ⑤ Fragility

경로가 몇 개의 취약한 전제에 의존하는가.

```text
fragility = 핵심 미확인 조건과 반증 위험

```

예:

```text
Belief: 높음
Impact: 높음
Applicability: 중간
Activation: 초기
Fragility: 높음

```

이 표현은 단일 `0.64`보다 훨씬 정보량이 많다.

---

## 3-7. 질문 목적에 따라 랭킹 기준을 바꾼다

모든 질문에 하나의 path score를 사용할 필요가 없다.

### “가장 가능성 높은 시나리오는?”

```text
belief × applicability × activation

```

### “가장 큰 상방을 만들 수 있는 경로는?”

```text
impact × applicability

```

단 belief가 최소 기준 이하이면 제외한다.

### “어디서 논리가 깨질 가능성이 큰가?”

```text
fragility 높은 순

```

### “아직 시장이 덜 보고 있는 수혜주는?”

```text
impact × applicability × activation
- salience

```

### “가장 구조적인 변화는?”

```text
pace_layer 무거움
× belief
× 장기 applicability

```

즉 그래프는 하나지만 **질문에 따라 렌즈와 랭킹 함수가 달라진다.**

이 접근은 Explorer의 “사실은 그래프로, 프레임은 렌즈로”라는 원칙과도 잘 맞는다.

---

## 3-8. reasoning run을 1급 객체로 저장

다음과 같은 테이블 또는 JSON 캐시를 권한다.

```text
reasoning_runs
reasoning_paths

```

### reasoning run

```json
{
  "query": "미국 AI CAPEX 증가의 한국 수혜주는?",
  "as_of": "2026-07-24",
  "target_universe": "한국 상장사",
  "geo_context": ["미국", "한국", "글로벌"],
  "time_horizon": "12-24m",
  "ranking_mode": "beneficiary_discovery",
  "graph_version": "...",
  "created_at": "..."
}

```

### path trace

```json
{
  "nodes": [
    "미국 AI CAPEX 증가",
    "GPU 출하 증가",
    "HBM 수요 증가",
    "HBM 생산 투자 증가",
    "장비 발주 증가",
    "A사 수주 증가"
  ],

  "belief": "medium_high",
  "impact": "high",
  "applicability": "medium",
  "activation": "observed",
  "fragility": "medium_high",

  "weakest_edge": "HBM 생산 투자 → A사 장비 발주",
  "missing_evidence": [
    "A사의 해당 공정 장비 점유율",
    "고객사 CAPEX의 실제 발주 일정"
  ],
  "falsifiers": [
    "고객사가 기존 장비 재활용으로 신규 발주를 축소",
    "A사의 벤더 점유율 하락"
  ]
}

```

이렇게 해야 “왜 이 종목을 지목했는가?”를 완전히 재현할 수 있다.

---

# 4. As-is → To-be 요약


| 영역     | As-is                    | 한계                  | To-be                                     |
| ------ | ------------------------ | ------------------- | ----------------------------------------- |
| 엣지 가중치 | `confidence` 중심          | 확신·효과·반복근거 혼합       | `confidence`와 `effect_strength` 분리        |
| 범위     | geo·period 저장            | 실제 질문에 대한 적합도 계산 약함 | scope는 저장, applicability는 질의 시 계산         |
| 경로 랭킹  | confidence 곱             | 믿을 만함과 중요함 혼동       | belief·impact·applicability·activation 분리 |
| 관계 유형  | CAUSES와 BENEFITS_FROM 순회 | 변수 인과와 기업 수혜 압축 혼합  | EXPOSED_TO 도입, BENEFITS_FROM 의미 명확화       |
| 근거 축적  | 재적재·내러티브 반복으로 강화         | 동일 원천 재인용 가능        | 독립 근거 원장과 independence group              |
| 동적 상태  | claim graph 중심           | 현재 경로 활성 여부 불명확     | observations로 activation 계산               |
| 결과 설명  | top path와 서사             | 경로 선택 근거 분해 부족      | reasoning run과 weakest edge·falsifier 저장  |
| 최종 점수  | 단일 scalar에 가까움           | 거짓 정밀 및 의미 불명확      | 다차원 assessment, 질문별 랭킹                    |


---

# 5. 기대 효과

## 5-1. “믿을 만한 경로”와 “중요한 경로”를 구분한다

현재는 confidence가 높은 경로가 우선된다.

To-be에서는 다음을 동시에 말할 수 있다.

```text
경로 A:
근거는 강하지만 실적 영향은 작다.

경로 B:
근거는 아직 약하지만 성립하면 실적 영향은 크다.

```

이는 투자자에게 훨씬 중요한 구분이다.

---

## 5-2. 수혜주 오탐을 줄인다

현재는 논리상 연결된 산업이나 기업을 지목할 수 있지만, 실제 노출도와 지역·시점 적합도가 약한 기업도 포함될 수 있다.

To-be에서는:

```text
인과적으로 연결됨
≠
현재 이 회사가 실질적으로 수혜를 받음

```

을 구분한다.

예를 들어 HBM 시장이 성장해도 모든 반도체 장비사가 동일한 수혜를 받는 것이 아니다. 공정 노출, 고객사, 매출 비중, 벤더 점유율, 발주 시차를 적용 가능성에 반영하게 된다.

---

## 5-3. LLM의 역할을 더 좁고 명확하게 만든다

현재 LLM은 인과 추출뿐 아니라 문맥 적합도와 경로 중요도를 최종 서사 안에서 암묵적으로 판단한다.

To-be에서는:

```text
기계적 부분:
범위 대조, 노출도 조회, 근거 집계, 경로 계산

LLM 부분:
메커니즘 해석, 누락 조건 제안, 반대 시나리오, 자연어 설명

인간 부분:
중요 가설 승인, 강도 수정, 투자 판단

```

으로 나뉜다.

이는 “기계는 제안, 사람이 판단”이라는 원칙을 실제 계산 구조에도 적용한다.

---

## 5-4. 반증 시스템이 더 정교해진다

현재 반증은 지식이나 가설에 붙는다.

To-be에서는 경로의 가장 약한 연결고리를 직접 감시할 수 있다.

```text
AI CAPEX 증가
→ HBM 수요 증가
→ 고객사 신규 팹 투자
→ A사 장비 발주

```

여기서 핵심 약점이:

```text
고객사 신규 팹 투자 → A사 장비 발주

```

라면, 시스템은 A사 벤더 점유율·장비 인증·수주 공시·고객사 발주 일정만 집중 감시할 수 있다.

즉 반증이 추상적 가설 수준에서 **경로의 병목 엣지 수준**으로 내려간다.

---

## 5-5. 같은 그래프를 여러 목적에 재사용할 수 있다

현재 그래프는 주로 내러티브와 수혜 파급에 사용된다.

To-be에서는 같은 그래프로 다음을 수행할 수 있다.

```text
가장 가능성 높은 시나리오
가장 큰 상방 경로
가장 취약한 투자 논리
아직 덜 회자된 수혜주
현재 활성화된 구조적 변화
지역 간 충격 전이
포트폴리오 공통 위험요인

```

그래프 데이터가 늘어날수록 질의 기능이 비선형적으로 확장된다.

---

## 5-6. Explorer의 철학과 구현이 더 일치한다

현재 철학은 이미 “분리해서 쌓는다”라고 선언한다.

하지만 `confidence` 하나에는 아직 여러 의미가 섞여 있다.

To-be는 이 원칙을 인과 reasoning 자체에 적용한다.

```text
확신과 영향 분리
scope와 applicability 분리
주장과 근거 분리
정적 관계와 현재 활성 상태 분리
인과 연결과 기업 노출 분리
탐색 점수와 투자 판단 분리

```

결국 시스템의 설명 가능성이 좋아지는 정도가 아니라, **철학과 데이터 모델의 불일치가 해소된다.**

---

# 6. 구현 우선순위

전면 재구축은 권하지 않는다. 아래 순서가 현실적이다.

## Phase 1 — 의미 정리와 최소 스키마 확장

가장 먼저 할 일이다.

### 변경

- `confidence` 정의를 “인과 주장의 신뢰도”로 한정
- `effect_direction` 추가
- `effect_strength` 범주형 추가
- `conditions_json` 추가
- 필요하면 `lag_min/max` 추가
- 기존 confidence 곱 결과를 `path_confidence`로 명칭 변경
- UI에서 이를 “영향도”가 아니라 “경로 신뢰도”로 표시

### 기존 기능 영향

작다. 기존 경로 탐색을 유지하면서 의미만 정직하게 바꿀 수 있다.

### 즉시 얻는 효과

- confidence의 의미 혼란 해소
- 거짓 정밀 감소
- 기존 결과를 깨지 않고 후속 확장 가능

---

## Phase 2 — reasoning trace 도입

### 변경

경로 반환 형식을 다음처럼 확장한다.

```json
{
  "path_confidence": "...",
  "effect_strength": "...",
  "scope_match": "...",
  "weakest_edge": "...",
  "missing_conditions": [],
  "falsifiers": []
}

```

초기 applicability는 완전한 수치 계산이 아니라 규칙 기반 범주로 시작한다.

```text
high / medium / low / unknown

```

### 즉시 얻는 효과

- 왜 이 경로가 선정됐는지 설명 가능
- 리포트와 시나리오의 근거 일관성 개선
- 사람이 승인할 때 취약점을 빠르게 파악

---

## Phase 3 — 기업 exposure 모델

### 최소 시작점

```text
company_exposures

```

```json
{
  "company_id": 123,
  "factor_entity_id": 456,
  "exposure_type": "revenue",
  "direction": "positive",
  "strength": "high",
  "geo_scope": ["미국"],
  "reference_period": "2026",
  "source_doc_id": 789,
  "epistemic_type": "hypothesis"
}

```

처음부터 모든 기업을 채우지 않고 리포트 대상·유니버스 기업부터 채운다.

### 효과

- 수혜주 지목 정밀도 상승
- `BENEFITS_FROM`의 숨은 전제를 노출
- 유니버스 밖 신규 후보 발굴의 품질 개선

---

## Phase 4 — 근거 원장과 독립성 관리

### 변경

- `relation_evidence` 도입
- `independence_group` 또는 `source_family` 도입
- 동일 원천 재인용을 하나로 묶음
- support/refute를 별도 저장
- confidence 갱신 이유를 설명 가능하게 함

### 효과

- 말뭉치 최신편향뿐 아니라 **말뭉치 복제편향**도 줄어듦
- 지식 승격의 신뢰성 향상
- contested/corroborated 판정 품질 개선

---

## Phase 5 — observations를 통한 activation

컨콜 프록시, 무역통계, 가격, 컨센서스, 공시를 인과 경로의 현재 활성 상태와 연결한다.

```text
구조적으로 가능한 경로
+
현재 관측으로 활성화된 경로
=
실제로 주목할 경로

```

### 효과

- 월드모델이 정적 온톨로지에서 살아 있는 시장 모델로 발전
- 홈의 delta UX와 직접 연결
- “무엇이 바뀌었는가?”를 인과 경로 단위로 보여줄 수 있음

---

# 7. 하지 말아야 할 것

## 모든 항목을 0~1 숫자로 만들지 않는다

다음과 같은 모델은 피해야 한다.

```text
confidence = 0.72
strength = 0.81
applicability = 0.63
activation = 0.76
최종 점수 = 0.578

```

정교해 보이지만 실제로는 LLM의 주관적 숫자를 조합한 것일 수 있다.

초기에는 범주형과 이유를 중심으로 둔다.

```text
신뢰도: 높음
영향: 강함
적용 가능성: 중간
활성 상태: 초기
취약점: 고객사 발주 전환 여부

```

---

## applicability를 엣지에 저장하지 않는다

applicability는 다음에 따라 달라진다.

- 대상 기업
- 질문
- 시점
- 투자 기간
- 지역
- 시나리오
- 현재 관측

따라서 정적 엣지 필드가 아니라 reasoning 결과다.

---

## 관계 유형을 한 번에 지나치게 세분화하지 않는다

처음부터 수십 개의 relation type을 만들면 LLM 추출 일관성이 무너지고 어휘 파편화가 커진다.

우선은 다음 정도면 충분하다.

```text
CAUSES
EXPOSED_TO
BENEFITS_FROM
MEMBER_OF

```

그리고 `CAUSES`에 방향·강도·조건을 붙인다.

---

## 기존 confidence 기반 순회를 바로 폐기하지 않는다

현재 순회는 이미 작동하고 있고, 내러티브·메르 서사·세계관 뷰와 연결되어 있다.

따라서:

```text
기존 경로 점수
→ path_confidence로 의미를 명확히 변경

새 impact/applicability
→ 병렬로 추가

충분히 검증 후
→ 질문별 복합 랭킹 도입

```

순서가 안전하다.

---

# 최종 제안

Explorer의 As-is를 한 문장으로 표현하면:

> **출처·시간·장소·인식론이 붙은 인과 가설을 축적하고, confidence 기반으로 multi-hop 경로를 탐색해 내러티브와 투자 시나리오를 만드는 시스템.**

내가 본 핵심 한계는:

> **confidence가 믿음·효과·반복 근거의 역할을 겸하고, scope와 대상 노출이 경로 랭킹에서 명시적으로 결합되지 않아, 가장 믿을 만한 경로와 가장 중요한 경로와 현재 적용되는 경로가 섞일 수 있다는 것.**

제안하는 To-be는:

> **인과 주장, 근거, scope, 대상 노출, 현재 관측을 분리 저장하고, 질의 시 belief·impact·applicability·activation·fragility를 계산하여 reasoning trace로 반환하는 구조.**

가장 중요한 변화는 스키마 필드 몇 개보다 이것이다.

```text
As-is:
“이 경로의 점수는 0.64다.”

To-be:
“이 경로는 근거는 강하고 영향도 크지만,
현재 대상에 대한 적용은 부분적이며,
고객사 발주 전환이라는 한 연결고리에 크게 의존한다.”

```

이 변화가 Explorer를 단순한 “인과 그래프가 있는 리서치 앱”에서 **가설의 강점·취약점·적용 조건까지 추적하는 투자 reasoning engine**으로 바꾼다.