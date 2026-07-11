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

## E. 열린 질문 (stakeholder 논의)

1. 승격을 자동 확정할까, 별칭처럼 **승인 큐**로 둘까? (초기엔 승인 큐 추천 —
   홈의 '승인 대기' 패턴이 이미 있고, 품질 관찰 후 자동화)
2. pace_layer 5층 명명이 투자 직관에 맞는가? (event/flow/cycle/structure/regime)
3. contested 알림의 피로 관리 — 임계값을 어디에?

---

### Sources
- [Why There Are Complementary Learning Systems in the Hippocampus and Neocortex (McClelland et al.)](https://www.researchgate.net/publication/15575602_Why_There_are_Complementary_Learning_Systems_in_the_Hippocampus_and_Neocortex_Insights_from_the_Successes_and_Failures_of_Connectionist_Models_of_Learning_and_Memory) · [A Neural Model of Schemas and Memory Consolidation](https://www.biorxiv.org/content/10.1101/434696v1.full)
- [ACT-R base-level learning (Petrov, CMU)](http://act-r.psy.cmu.edu/wordpress/wp-content/uploads/2012/12/652petrovAbstract.pdf) · [Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture](https://dl.acm.org/doi/10.1145/3765766.3765803)
- [The Wisdom of Crowds (Surowiecki) — 4조건·정보 캐스케이드](https://en.wikipedia.org/wiki/The_Wisdom_of_Crowds)
- [Analysis of Competing Hypotheses (Heuer)](https://en.wikipedia.org/wiki/Analysis_of_competing_hypotheses) · [Improving Intelligence Analysis with ACH](https://pherson.org/wp-content/uploads/2013/06/Improving-Intelligence-Analysis-with-ACH.pdf)
- [Pace Layering: How Complex Systems Learn (Brand, MIT JoDS)](https://jods.mitpress.mit.edu/pub/issue3-brand) · [Pace layers — Long Now](https://longnow.org/ideas/pace-layers/)
- [The Half-Life of Facts (Arbesman)](https://fs.blog/the-half-life-of-facts/) · [서평·mesofacts](https://www.themarginalian.org/2012/11/06/the-half-life-of-facts/)
