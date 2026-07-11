# 지식 위계 설계 — 관찰, 종합, 스키마 (knowledge-system.md ②의 설계 게이트 산출물)

> 2026-07-11. 상태: **설계 초안 — stakeholder 리뷰 대기.** 구현은 문서 1,000건 게이트 유지.
> 방법: 인간 기억·집단 지성·세계의 시간 구조에 대한 확립된 이론을 조사하고,
> 각 원리를 Explorer의 실체(테이블·파이프라인)에 번안한다. 이론은 장식이 아니라
> 설계 결정의 근거로만 인용한다.

---

## A. 관찰 — 세 영역의 원리와 시사점

### A-1. 인간 기억은 이중 시스템이다 (CLS 이론)

**원리**: 기억은 두 시스템의 협업이다 — 해마는 개별 사건을 빠르게, 겹치지 않게
저장하고(사례 기억), 신피질은 수많은 사례를 가로지르는 규칙성을 천천히 학습한다
(스키마). 해마가 기억을 재생(replay)하면서 신피질로 점진 이관하는 것이 '공고화
(consolidation)'다. 기존 스키마와 일치하는 새 정보는 느린 학습을 건너뛰고 빠르게
편입된다.

**시사점**:
- 우리의 `raw_documents`가 해마(사례), 아직 없는 **knowledge 계층이 신피질(스키마)**.
  지금 시스템은 해마만 있고 공고화가 없다 — 모든 지식이 영원히 '개별 사건'으로 남는다.
- 공고화 = **승격 배치**: 반복 관측된 주장을 사례에서 지식으로 이관.
- "스키마 일치 시 빠른 편입" = 이미 승격된 지식과 일치하는 새 관측은 corroboration
  카운트만 올리면 된다 (재승격 불필요 — 싸다).

### A-2. 기억의 강도는 빈도×최신성의 함수다 (ACT-R 활성화)

**원리**: 기억 인출 확률은 활성화(activation)로 결정되고, 기저 활성화는
**B = ln(Σ tⱼ⁻ᵈ)** — 각 과거 노출 j의 경과시간 t에 감쇠지수 d를 적용해 합산한다.
"자주, 그리고 최근에 쓰인 기억일수록 강하다." 망각은 삭제가 아니라 접근성의
하락이며, 새로운 노출 한 번이 오래된 기억을 되살린다(재활성화). 여기에 맥락
연상(Σ Wⱼ·Sⱼᵢ)이 더해져 현재 상황과 연결된 기억이 우선 인출된다.

**시사점** (이 설계의 수학적 심장):
- 지식 항목의 **activation을 저장하지 않고 조회 시 계산**한다 — 증거(evidence)
  타임스탬프들에 ln(Σ t⁻ᵈ)를 적용. 감쇠 배치 작업이 필요 없어진다 (시간이 지나면
  자동으로 약해지고, 새 증거 한 건이 자동으로 되살린다 = 재활성화 공짜).
- **d(감쇠율)는 지식마다 다르다** → A-5의 pace layer가 d를 결정.
- "정서적 각성이 기억을 강화한다"의 우리 대응물: **사용자 행위** — 질문·논지 기록·
  팔로우가 닿은 지식은 가중 노출로 취급 (사용자의 주의 = salience).
- 소비 지점(RAG 랭킹)에서 relevance × activation — 관련돼도 죽은 지식은 뒤로,
  약해도 방금 되살아난 지식은 앞으로.
- **연상 활성화 항(Σ Wⱼ·Sⱼᵢ)의 번안 — 역사 소환** (v4 추가): base-level만으로는
  재활성화가 수동적이다(새 문서가 옛 지식에 명시 연결돼야 소환). 금융 기억의
  극단적 짧음(Galbraith)이 실수 반복을 낳는 이유가 이것 — 시장이 조용히 같은
  패턴으로 미끄러질 때 소환 트리거가 없다. 보완: **현재 국면과 과거 국면의
  유사성 자체가 소환 신호** (프로세스 7).

### A-3. 집단의 지혜는 독립성이 만든다 (Surowiecki 4조건)

**원리**: 군중이 전문가보다 정확해지는 조건은 넷 — 의견의 **다양성**, 판단의
**독립성**, **분산**된 국지 지식, 효과적 **집계**. 이 중 독립성이 무너지는 순간
(서로의 판단을 보고 따라하는 정보 캐스케이드) 집계의 가치가 붕괴한다 — 100개의
목소리가 사실상 1개의 목소리가 된다.

**시사점**:
- **corroboration은 소스 수가 아니라 독립 관측 수다.** 텔레그램 생태계는 같은
  속보를 여러 채널이 재방송한다(릴레이) — 이건 5개 소스가 아니라 1개 관측이다.
  독립성 판별: ⓐ 소스 유형이 다른가(텔레그램 vs 블로그 vs 공시 vs 내 노트)
  ⓑ 문서 유사도가 높으면 동일 관측으로 접기 (doc_vec 재사용) ⓒ 시간차.
- 우리의 **에코챔버 방지 원칙(AI 답변 비색인)은 정보 캐스케이드 차단의 특수형**이다
  — 시스템이 자기 출력을 관측으로 세면 캐스케이드의 극단이 된다. 같은 이유로
  승격된 지식도 증거로 재사용 금지 (지식은 증거를 인용하지, 증거가 되지 않는다).
- 다양성 자체가 신호다: 성격이 다른 소스들이 같은 주장을 하면 confidence가
  비선형적으로 올라간다.

### A-4. 가설은 반증으로 다룬다 (Heuer의 ACH)

**원리**: 정보분석의 구조적 기법 ACH는 가설을 '지지 증거의 수'가 아니라
'**반증되지 않은 정도**'로 평가한다. 모든 경쟁 가설을 명시적으로 유지하고,
각 증거가 어느 가설과 불일치하는지를 매트릭스로 따진다. 확증편향(마음에 드는
가설의 지지 증거만 수집)이 주적이다.

**시사점**:
- 지식 항목의 증거는 **support만이 아니라 refute도 기록**한다 (stance 컬럼).
- 모순된 증거가 나타나면 지우거나 덮어쓰지 않고 **contested 상태로 공존**시킨다 —
  합의가 뒤집히는 재료는 소수의견에서 나온다 (소수의견 보존).
- 이미 검증된 패턴의 일반화: 브리프의 thesis_check("논지는 지지되나 HBM4 근거는
  문서에 없다")가 정확히 ACH의 축소판 — 이걸 사용자 논지만이 아니라 승격된
  지식 전체에 적용하는 것이 모순 감지 프로세스다.

### A-5. 세계는 속도가 다른 층으로 움직인다 (Pace Layering + 지식 반감기)

**원리**: Stewart Brand의 pace layers — 문명은 fashion(최속) → commerce →
infrastructure → governance → culture → nature(최저속)의 층으로 움직이고,
"**Fast learns, slow remembers.** Fast proposes, slow disposes." 층 간 마찰이
건강이다. Arbesman의 지식 반감기 — 지식은 방사성 붕괴처럼 측정 가능한 속도로
낡으며, 분야마다 반감기가 다르다 (물리학 논문 ~10년, 임상지식 ~45년). 대부분의
투자 지식은 한 세대 안에서 바뀌는 mesofact다.

**투자 도메인 번안** (pace layer → 감쇠율 d):

| 층 | 예 | 반감기 감각 | d |
|---|---|---|---|
| **event** | 상장 첫날 +12.8%, 오늘의 공시 | 일~주 | 큼 (빨리 잊음) |
| **flow** | 수급·분기 실적·컨센서스 | 주~분기 | 중상 |
| **cycle** | 메모리 사이클 국면, 금리 사이클 | 분기~년 | 중 |
| **structure** | HBM 경쟁구도, 지배구조, LTA 고착 | 년~수년 | 작음 |
| **regime** | 회계제도, 밸류업 정책, 기술 패러다임 | 수년~십년 | 최소 |

**시사점**:
- "오래됐지만 맥락적으로 유효한 지식"의 정체가 풀린다: **structure/regime 층의
  지식은 event 층의 시계로 재면 안 된다.** 2018년 메모리 사이클 지식(cycle 층)은
  2026년 사이클에서 재활성화될 자격이 있다 — A-2의 activation 식에서 낮은 d 덕에
  살아 있고, 새 문서가 연결되는 순간 앞으로 나온다.
- 층 분류는 승격 시 LLM이 제안하되 어휘는 고정 5개 (live vocab 방식의 반대 —
  여기는 닫힌 어휘가 맞다. 층은 세계관이지 태그가 아니다).
- "Fast learns, slow remembers": event 층은 다이제스트가 이미 담당한다.
  지식 계층의 존재 이유는 **cycle 이하의 느린 층** — 빠른 층을 승격하려고
  애쓰지 않는다 (event는 승격 대상에서 원칙적으로 제외).

### A-6. 인간 지능의 편향은 모방하지 않고 보정한다 (행동경제학 + Marks의 진자)

**원리**: 인간 기억의 강점(강도·감쇠·공고화)을 빌리되, 그 시스템의 실패 모드는
설계로 상쇄해야 한다. 행동경제학이 목록화한 실패들 — 가용성 휴리스틱(최근·생생한
것의 과대평가), 확증편향, 앵커링, 손실회피 — 과 Howard Marks의 진자(pendulum):
시장 심리는 낙관↔비관의 극단을 오가며 중간에 머물지 않고, **모두가 동의하는
순간이 가장 위험하다.** 군중심리는 A-3의 독립성 붕괴가 감정 차원에서 일어난 것.

**시사점 — 편향별 보정 장치**:
| 인간의 편향 | 이 시스템에서의 발현 | 보정 |
|---|---|---|
| 가용성 휴리스틱 | activation의 최신성 편중 | pace layer 분리 표기 — "지금 시끄러운 것"(event)과 "구조적인 것"(structure)을 소비 지점에서 섞지 않는다 |
| 확증편향 | 지지 증거만 수집·승격 | 승격 시 **반대 증거 탐색 의무화** (해당 주장 부정 검색 1회) + refute stance (A-4) |
| 앵커링 | 낡은 추정·목표가에 고정 | valid_to·supersedes 계보 — '언제까지 참이었나'가 일급 정보 |
| 군중 극단 (진자) | 소스 전체가 한 방향으로 쏠림 | **진자 감시(프로세스 6)**: 엔티티별 sentiment 집계가 극단(만장일치)에 도달하면 그 자체를 신호로 — 컨센서스의 강도가 역설적 경고 |

### A-7. 격자식 사고 — 렌즈의 교차점 (Munger)

**원리**: Charlie Munger의 latticework of mental models — 하나의 현상을 여러
분과의 모델(심리학·경제학·공학…)로 겹쳐 볼 때 판단이 강해지고, 여러 모델이
같은 방향을 가리키는 교차점에서 비선형적 효과(lollapalooza)가 난다.

**시사점**: 이 시스템의 격자는 이미 두 축으로 존재한다 — **도메인 렌즈**(live vocab
라벨: 매크로·지정학·산업·수급·기술 — 정치외교/거시/기술 관점은 여기서 커버되며,
어휘가 살아있으므로 관점 축은 계속 자란다)와 **시간 층**(pace layer). 격자는 이
둘의 곱이다. 설계 반영: 승격된 지식이 **여러 도메인 라벨에 걸칠 때(교차 도메인)
주목 가중** — 지정학×반도체×수급이 같은 방향을 가리키는 지식은 단일 렌즈 지식보다
중요할 개연성이 높다. (단, 가중은 보수적으로 — lollapalooza는 드물어서 가치 있다.)

---

## B. 종합 — Explorer 지식 위계 모델

### 3계층 구조

```
records   원문서 (raw_documents)            — 해마: 사례, 전량 보존, 불변
   ↓ 태깅 (기존 enrich)
claims    문서 속 주장 (entity_links 수준)   — 아직 개별 관측
   ↓ 승격 (주간 배치: 반복 × 독립성)
knowledge 통합 지식                          — 신피질: 스키마, 느린 층 중심
```

### 지식 항목의 해부

```
statement        "SK하이닉스는 HBM 공급을 LTA로 고착화해 고객 이탈 비용을 높였다"
entities         [SK하이닉스(subject), HBM(topic)]
epistemic_status observed → corroborated → contested → superseded   (+ hypothesis: 사용자/AI 가설)
pace_layer       structure                                          (닫힌 어휘 5개 → 감쇠율 d)
evidence         [(doc 132, support, 독립), (doc 264, support, 비독립·릴레이), (doc 501, refute, 독립)]
activation       조회 시 계산: ln(Σ t⁻ᵈ) — 증거·사용자행위 타임스탬프 기반
valid_from/to    유효 구간 — superseded 시 to를 닫음 (삭제 금지)
supersedes       계보 — 어떤 지식을 대체했는가
```

### 프로세스 다섯 (전부 기존 패턴의 연장)

1. **승격** (주 1회 haiku 배치): 최근 창의 claims에서 ⓐ 독립 관측 2+ ⓑ event 층
   아님 ⓒ 기존 지식과 중복 아님 → 후보 생성, **증거 doc_id 인용 강제** (인용 없는
   승격은 폐기 — 환각 방어). 기존 지식과 일치하면 corroboration만 증가 (A-1).
2. **모순 감지**: 새 문서가 기존 지식과 불일치하면 refute 증거로 부착 →
   임계 초과 시 contested → 홈 브리핑 "지식 충돌" 알림 (thesis_check의 일반화).
3. **감쇠**: 배치 없음 — activation이 조회 시 계산이므로 자동 (A-2).
4. **재활성화**: 새 증거·사용자 행위가 붙는 순간 activation 식이 자동 반영.
5. **소멸**: superseded — valid_to 닫고 계보 연결. 삭제는 없다 (역사가 맥락이다).
6. **진자 감시** (A-6, K2+): 엔티티별 최근 창의 sentiment 분포가 극단(예: 일방향
   90%+ & 표본 충분)이면 "컨센서스 극단" 신호 생성 — 낙관의 만장일치는 경고다.
7. **역사 소환** (A-2 연상 항, K2+): 현재 국면 벡터(최근 창의 신호·감성·라벨 분포)를
   과거 시점 창들과 대조 — 유사 국면이 발견되면 그 시기의 cycle/structure 지식을
   능동 소환해 브리핑에 "유사 국면: 20XX년 X월 — 그때의 교훈" 항목으로.
   과거의 실수를 되풀이하지 않는 것은 기억의 존재가 아니라 **소환의 타이밍**이다.

### 소비 지점

- **RAG**: 검색 컨텍스트에 knowledge 계층 추가 (문서 발췌와 별도 블록,
  "[승격된 지식 · corroborated · structure층]" 라벨). 랭킹 가중:
  relevance × f(activation) × g(epistemic — corroborated > observed > contested).
- **브리프/다이제스트**: 관련 지식을 재료 블록으로 (근거 재료 칩에 "지식 N건" 추가).
- **홈**: contested 전환·승격 완료가 브리핑 항목으로.
- **사용자 주입 지식(①)**: hypothesis로 시작 — 수집 문서가 독립 확인하면
  corroborated로 승격 (사람과 기계의 지식이 같은 수명주기를 산다).

## C. 스키마 매핑 (신규 3테이블 — 기존 테이블 무변경)

```sql
knowledge (
  id, statement TEXT, epistemic_status TEXT, pace_layer TEXT,
  confidence REAL, valid_from TEXT, valid_to TEXT,
  supersedes INTEGER REFERENCES knowledge(id), model TEXT, created_at TEXT
)
knowledge_entities (knowledge_id, entity_id, role TEXT)         -- subject|object|context
knowledge_evidence (
  knowledge_id, doc_id, stance TEXT,                            -- support|refute
  independent INTEGER,                                          -- 독립 관측 여부 (A-3 판별)
  observed_at TEXT                                              -- activation 계산의 t
)
-- 사용자 행위 가중: knowledge_evidence에 doc_id NULL + stance='attention' 행으로 기록
```

entity_relations(관계형 지식)·observations(수치)는 knowledge의 특수형으로 병행 유지
— 무리하게 통합하지 않는다 (승격 배치가 관계형이면 entity_relations에, 서술형이면
knowledge에 쓴다).

## D. 구현 단계와 게이트

| 단계 | 내용 | 게이트 |
|---|---|---|
| K0 | 테이블 + 승격 배치(주 1회) + 독립성 판별 | **문서 1,000건** + 본 설계 승인 |
| K1 | RAG·브리프에 knowledge 소비 통합 | K0 후 승격 품질 육안 검증 2주 |
| K2 | 모순 감지 → contested → 홈 알림 | K1 |
| K3 | 사용자 주입 지식의 corroboration 승격 | K1 |

**검증 골든 케이스** (K0 출시 판정 기준):
- SKHY ADR 반복 관측(30+ 문서)에서 "펀저빌리티 구조" 같은 structure층 지식이 승격되는가
- 텔레그램 릴레이(동일 속보 5채널)가 독립 관측 1로 접히는가
- "상장 첫날 +12.8%"(event층)가 승격되지 **않는가**

**리스크**: LLM 승격 환각(→증거 인용 강제 + 승인 대기 큐 노출 — 홈의 승인 패턴 재사용),
statement 파편화(→승격 시 기존 지식 목록 주입, live vocab 방식), 비용(주 1회 haiku
수십 콜 — 규약 ⓐ급).

## E. 결정 사항 (2026-07-11 stakeholder 확정)

1. **승격은 승인 큐** — 홈에 전용 승인 카드 (항목별 인라인 승인/거부, 별칭 제안과
   동일 표면). 품질 관찰 후 자동화 재논의. → 승인 큐 UI는 게이트와 무관하게 선행
   구현 (별칭 제안이 첫 사용자).
2. **5층 유지** (event/flow/cycle/structure/regime) — 단 A-6의 편향 보정 장치와
   반드시 함께 (인간 직관에 맞다 = 인간 편향도 담겼다는 뜻이므로).
3. **contested 알림**: 전환 시 즉시 1회, 같은 지식 재알림은 7일 쿨다운, 브리핑
   노출은 하루 최대 1건 (가장 activation 높은 것).

---

## G. 지향점 — 통념과 가설의 갭 (stakeholder 투자관, 2026-07-12)

> "투자는 언제나 '시장의 통념·기대'와 '나의 가설·확률에 따른 포지션 조정' 간의
> 갭을 줄다리기하는 싸움이다."

이 시스템의 최종 소비 형태는 이 갭의 상시 계량이다:

```
시장의 통념  = corroborated 지식 (집단 지성 집계) + 진자 위치 (감성 분포) + 컨센서스 추정
나의 가설    = hypothesis 계층 (논지·주입 지식) + 포지션 (워치리스트·확신)
      갭     = 둘의 대조 — thesis_check의 전면 일반화
```

갭이 넓고 내 가설의 증거가 쌓이면 기회, 갭이 닫히면(통념이 내 가설을 따라오면)
엣지 소진 신호, 통념이 극단인데 내 가설이 없으면 진자 경고. 모든 프로세스(승격·
모순·진자·역사 소환)는 이 갭 계량의 입력이다.

---

## F. 문헌 검증 (2026-07-12 조사) — 확증·도전·수정

설계를 각 분야의 고인용 정본 연구에 대조한 결과. **판정**: ✅확증 ⚠️도전 ➕설계 수정.

| 문헌 | 분야 | 요지 | 판정 |
|---|---|---|---|
| **Anderson & Schooler (1991)** *Reflections of the Environment in Memory* — ACT-R의 실증 기반 | 인지심리 | 기억 가용성은 환경의 재사용 확률(need odds)을 미러링하며, NYT 헤드라인·이메일 등 실환경에서 빈도·최신성·**노출 패턴**의 power law를 실측 | ✅ ln(Σt⁻ᵈ)가 임의 선택이 아니라 환경 통계에 최적화된 형태임을 실증. ➕ **간격 효과**: 몰아친 N회 노출 < 시간에 분산된 N회 — 승격 기준 수정 (아래) |
| **Kahneman & Tversky (1974)** *Judgment under Uncertainty* (Science) · **(1979)** *Prospect Theory* (Econometrica 역대 최다 인용) | 행동경제 | 가용성·대표성·앵커링 휴리스틱과 편향 목록; 손익 비대칭(손실회피) | ✅ A-6 보정표의 정본 근거. ➕ 손실회피 → 진자 감시에서 **비관 쏠림은 낙관보다 빠르고 깊게 형성** — 임계 비대칭 참고 |
| **HippoRAG (NeurIPS 2024)** — 해마 인덱싱 이론 기반 LLM 장기기억 | AI | LLM+지식그래프+Personalized PageRank로 신피질/해마 역할 분담 — multi-hop QA +20%, 반복검색 대비 10-30배 저렴 | ✅ CLS→시스템 매핑이 업계 검증된 방향. ⚠️ 승격만이 신피질이 아니다 — **그래프를 통한 검색 확산**도 스키마 역할 → K1에 entity_links 그래프 확산 검토 추가 |
| **Generative Agents (Park et al. 2023, UIST)** — 에이전트 메모리의 정본 | AI | 검색 점수 = recency(지수감쇠)×importance×relevance; 주기적 reflection으로 상위 지식 종합 | ✅ 우리 activation×relevance와 동형, reflection=승격의 선례. ⚠️ 그들의 importance는 **LLM 단건 채점** — 우리는 corroboration(독립 관측 수)으로 도출: 더 검증가능하고 환각에 강함 (설계 유지, 차이 명시) |
| **LLM 에이전트 메모리 생태계 (2025-26 서베이·Mem0·Zep·Letta)** | AI | 업계가 episodic/semantic/procedural 3층으로 수렴; Zep은 그래프+하이브리드 검색을 **검색 시 LLM 무호출**로; MemGuard 등 'memory contamination'이 공인 문제 | ✅ records/claims/knowledge ≈ episodic→semantic 수렴과 정합. ✅ '조회 시 계산·검색 시 LLM 0' 방향 확증. ✅ 에코챔버 방지(오염 차단)가 업계 공인 문제임을 확인 |
| **Hayek (1945)** *The Use of Knowledge in Society* (AER) | 경제학 | 지식은 분산·국지적·암묵적이며 어떤 단일 주체도 전체를 가질 수 없다 — 문제는 자원 배분이 아니라 **분산 지식의 조정** | ✅ 이 시스템의 존재 이유에 대한 헌장 (분산 소스의 국지 지식 집계). ➕ **국지성 가중**: 소스가 자기 전문 영역에서 말할 때 가중 — 소스 도시에의 '주로 다루는 것'이 이미 전문성 프로파일이므로 승격 시 활용 가능 |

### 문헌이 요구한 설계 수정 (v3)

1. **승격 기준에 간격 요건 추가** (Anderson & Schooler): 독립 관측 2+ **이면서 시간
   분산** — 같은 날 쏟아진 관측 묶음은 1개 에피소드로 취급 (몰림 ≠ 반복 확인).
2. **K1에 그래프 검색 확산 검토** (HippoRAG): 승격된 지식·entity_links 위에서
   개인화 PageRank류 확산 — 검색 시 LLM 무호출 원칙 유지 (Zep 실증).
3. **진자 감시 임계 비대칭** (손실회피): 비관 쏠림의 형성 속도·깊이가 크므로
   낙관 만장일치 임계를 더 민감하게 (역설적으로 낙관 극단이 더 드물고 더 위험).
4. **국지성 가중** (Hayek): 승격 증거 평가에서 소스의 전문 영역 일치 여부를
   corroboration 품질에 반영 (K0에서는 기록만, 가중은 K1+).

### Sources
- [Why There Are Complementary Learning Systems in the Hippocampus and Neocortex (McClelland et al.)](https://www.researchgate.net/publication/15575602_Why_There_are_Complementary_Learning_Systems_in_the_Hippocampus_and_Neocortex_Insights_from_the_Successes_and_Failures_of_Connectionist_Models_of_Learning_and_Memory) · [A Neural Model of Schemas and Memory Consolidation](https://www.biorxiv.org/content/10.1101/434696v1.full)
- [ACT-R base-level learning (Petrov, CMU)](http://act-r.psy.cmu.edu/wordpress/wp-content/uploads/2012/12/652petrovAbstract.pdf) · [Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture](https://dl.acm.org/doi/10.1145/3765766.3765803)
- [The Wisdom of Crowds (Surowiecki) — 4조건·정보 캐스케이드](https://en.wikipedia.org/wiki/The_Wisdom_of_Crowds)
- [Analysis of Competing Hypotheses (Heuer)](https://en.wikipedia.org/wiki/Analysis_of_competing_hypotheses) · [Improving Intelligence Analysis with ACH](https://pherson.org/wp-content/uploads/2013/06/Improving-Intelligence-Analysis-with-ACH.pdf)
- [Pace Layering: How Complex Systems Learn (Brand, MIT JoDS)](https://jods.mitpress.mit.edu/pub/issue3-brand) · [Pace layers — Long Now](https://longnow.org/ideas/pace-layers/)
- [The Half-Life of Facts (Arbesman)](https://fs.blog/the-half-life-of-facts/) · [서평·mesofacts](https://www.themarginalian.org/2012/11/06/the-half-life-of-facts/)
- Howard Marks, *Mastering the Market Cycle* / memo "On the Couch" — 진자·컨센서스 극단 · Charlie Munger, *Poor Charlie's Almanack* — latticework of mental models (stakeholder 제안 반영)
- [Anderson & Schooler (1991) Reflections of the Environment in Memory](https://journals.sagepub.com/doi/abs/10.1111/j.1467-9280.1991.tb00174.x) · [원문 PDF](https://users.cs.northwestern.edu/~paritosh/papers/KIP/AndersonSchooler1991ReflectionsOfEnvironmentOnMemory.pdf)
- [Tversky & Kahneman (1974) Judgment under Uncertainty (Science)](https://www.science.org/doi/10.1126/science.185.4157.1124) · [Prospect Theory (1979) 개관](https://en.wikipedia.org/wiki/Prospect_theory)
- [HippoRAG (NeurIPS 2024)](https://arxiv.org/abs/2405.14831) · [Generative Agents (Park et al. 2023)](https://arxiv.org/abs/2304.03442)
- [Memory in the Age of AI Agents: A Survey — paper list](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) · [From Storage to Experience: LLM Agent Memory Survey](https://arxiv.org/pdf/2605.06716) · [AI Agent Memory Architectures (2026)](https://zylos.ai/research/2026-04-05-ai-agent-memory-architectures-persistent-knowledge/)
- [Hayek (1945) The Use of Knowledge in Society (AER)](https://en.wikipedia.org/wiki/The_Use_of_Knowledge_in_Society) · [원문](https://oll.libertyfund.org/titles/hayek-the-use-of-knowledge-in-society-1945)
