# 시장·경기 국면 분류 방법 연구

> EXPLORER / RESEARCH NOTE 02 · 2026.10.26 자료 확인 기준
> 주제: 과거 시장 국면(강세·약세·조정)과 경기 국면(확장·침체, 성장×물가)을 결정론적 규칙으로 나누는 방법.
> 용도: 국면 타임라인 페이지, 그리고 "개별 종목(예: 버크셔 해서웨이)이 지수를 이긴 시기가 어떤 국면이었나" 같은 조건부 비교.

학술 논문, 지수 사업자·리서치 회사의 공식 정의, 운용사 백서를 우선 확인했습니다. 수치는 원문에서 직접 확인한 것만 적었고, 확인하지 못한 수치는 "미확인"으로 표시했습니다. 출처는 문서 끝의 ID(S01…)로 참조합니다.

---

## 01 / 핵심 판단

1. **국면 분류는 "언제 알 수 있었나"부터 정해야 한다.** 거의 모든 국면 정의는 사후(ex-post) 판정이다. 고점은 지수가 고점에서 20% 떨어진 뒤에야 고점이 되고, NBER 경기 고점은 평균 7.8개월 뒤에 발표된다 [S14]. 사후 라벨로 과거를 설명하는 것은 정당하지만, 그 라벨을 당시 판단 근거처럼 보여 주면 미래 정보 누설(look-ahead)이 된다. 그래서 국면마다 **사후 구간(peak→trough)**과 **확인 시점(confirm date)**을 함께 저장한다.
2. **과거 국면을 나누는 데는 규칙 기반 방법이 더 낫고, 앞으로를 예측하는 데는 통계 모형이 낫다.** Kole & van Dijk(2013)는 S&P 500에서 이를 직접 비교했다. 규칙 기반(Pagan-Sossounov, Lunde-Timmermann)은 표본 내 식별에서 유의하게 우월했고, 마르코프 국면전환 모형은 표본 외 예측에서 우월했다 [S04]. 이 앱의 목적은 예측보다 과거 국면 지도에 가깝다. 그러므로 가격 국면은 규칙 기반으로 정의한다.
3. **HMM·GMM 같은 추정 모형은 라벨 층으로 쓰지 않는다.** 데이터가 추가될 때마다 재추정되면 과거 라벨도 바뀐다. 상태 번호에 의미를 붙이는 일도 사람이 사후에 한다. Two Sigma도 자사 GMM 국면 모형이 "예측 모형이 아니다"라고 밝힌다 [S09]. 설명 가능성과 결정론을 요구하는 이 앱에서는 비교용 실험으로만 둔다.
4. **"약세장 = 고점 대비 −20%(종가)"는 학술 근거가 아니라 관행이다.** 다만 S&P Dow Jones Indices [S05]와 Yardeni [S06]가 공식적으로 쓰고, Lunde-Timmermann의 기본 임계값과도 같다 [S03][S04]. 그래서 가장 설명하기 쉬운 기준이다. 대신 1990년(−19.9%)이나 2018년(−19.8%)처럼 임계값을 간신히 넘지 못한 하락이 있다. 이런 하락은 "임계 근접 조정"으로 따로 보여 줘야 한다.
5. **버크셔 질문에는 시장 가격 국면 층이 맞다.** 가설("약세장에서 지수를 이긴다")이 시장 국면에 대한 주장이기 때문이다. 경기 국면(NBER)은 보조 축으로 둔다. 비교에는 총수익 지수를 써야 한다. `^GSPC`는 배당이 빠진 가격지수이고 버크셔는 배당이 없어서, 그대로 비교하면 버크셔의 초과수익이 매년 S&P 500 배당수익률만큼 부풀려진다.

---

## 02 / 방법 계열별 정리

각 항목은 정의 → 필요 데이터(무료 커버 여부) → 사후/실시간 → 장단점 → 사용처 순서로 정리했습니다.

### 2.1 강세·약세 연대 판정 알고리즘 (가격 기반 규칙)

#### A. "고점 대비 −20% / 저점 대비 +20%" 관행
- **정의**: 직전 고점 대비 종가 기준 20% 이상 하락하면 약세장이다 (S&P DJI, CNBC 2022 보도 [S05]). Yardeni는 "강세장 = −20% 이상 약세장 사이의 상승 구간"으로 정의한다. 조정은 관행상 −10% 이상이지만, Yardeni는 −5% 이상까지 조정 표에 넣는다 [S06].
- **데이터**: 지수 일별 종가. `^GSPC`는 1927-12-30부터, `^IXIC`는 1971-02-05부터 무료로 받을 수 있다 (yfinance 확인).
- **시점 문제**: 약세장으로 판정되는 날은 −20%를 처음 넘은 날이다. 하지만 약세장의 시작일은 그보다 앞선 고점으로 소급된다. 저점도 +20% 반등이 확인돼야 확정된다. 실시간으로 알 수 있는 것은 "현재 고점 대비 낙폭"뿐이다.
- **장점**: 업계 공용어라 설명이 쉽고, 공개 표(Yardeni)와 대조해 검증할 수 있다.
- **단점**: 임계값을 넘었는지 여부만 본다. 그래서 −19.9%(1990), −19.4%(2011), −19.8%(2018)는 모두 "약세장 아님"이 된다. 종가 기준인지 장중 기준인지에 따라 결과가 달라진다.
- **사용처**: S&P DJI, Yardeni Research, 대부분의 언론과 증권사 자료.

#### B. Ned Davis Research 정의
- **정의**: 다우지수(DJIA) 기준이다. 약세장은 50 달력일 동안 −30% 이상 또는 145 달력일 동안 −13% 이상 하락한 경우, 강세장은 50일 동안 +30% 이상 또는 155일 동안 +13% 이상 상승한 경우다 [S07].
- **특징**: 낙폭과 기간을 결합해 "느리지만 긴 하락"도 잡는다. 같은 데이터에서 −20% 기준보다 국면이 더 많이 나온다.
- **사용처**: Ned Davis Research(유료 리서치), Stock Trader's Almanac.

#### C. Lunde & Timmermann (2004) 필터 규칙
- **정의** [S03][S04]: 직전 저점 t₀ 이후의 최고가 대비 하락률이 λ₂를 넘으면, 그 최고가 시점을 고점으로 확정하고 약세 상태로 바꾼다. 직전 고점 이후의 최저가 대비 상승률이 λ₁을 넘으면, 그 최저가 시점을 저점으로 확정하고 강세 상태로 바꾼다.
- **파라미터**: 원 논문의 주 설정은 **λ₁ = 20%(→강세), λ₂ = 15%(→약세)**다. 15%를 쓴 이유는 주가의 양(+)의 드리프트를 반영하기 위해서다. 논문은 5~30% 범위에서 민감도도 보고했다 [S04]. R 패키지 bbdetection의 기본값은 15/15다 [S03].
- **데이터**: 지수 종가만 있으면 된다. 수익률 임계값을 쓰므로 일·주·월 빈도를 바꿔도 결과가 안정적이다 [S03].
- **시점 문제**: 전환 확정이 지연된다. Kole & van Dijk는 "LT 방식으로 약세장을 맞게 예측하는 데는 오래 걸리고, 때로 약세장의 절반 이상이 지난 뒤였다"고 썼다 [S04].
- **장점**: 규칙이 두 줄로 끝나서 결정론적이고 설명이 쉽다. −20% 관행을 일반화한 형태다.
- **사용처**: 학술 연구(지속기간 의존성 분석). bbdetection 등 공개 구현이 있다.

#### D. Pagan & Sossounov (2003) — Bry-Boschan 변형
- **정의** [S02][S03][S04]:
  1. 전후 τ_window 기간 안에서 가장 높은(낮은) 점을 고점(저점) 후보로 잡는다.
  2. 고점과 저점이 번갈아 나오도록 연속된 같은 종류 중 극값만 남긴다.
  3. 첫 τ_censor 기간과 마지막 τ_censor 기간의 전환점은 제거한다.
  4. τ_cycle보다 짧은 사이클은 제거한다.
  5. τ_phase보다 짧은 국면은 제거한다. 단, 변동폭이 θ를 넘으면 예외로 남긴다.
- **파라미터(월간)**: PS(2003)는 τ_window=8, τ_censor=6, τ_phase=4, τ_cycle=16, θ=20%를 썼다. Gonzalez 외(2005)는 6/6/5/15/20%를 썼다. Kole & van Dijk는 주간 데이터에 32주/70주/16주/20%를 적용했고, 끝단 검열은 13주로 줄였다 [S04].
- **시점 문제**: 끝단 검열 때문에 최근 6개월(주간 설정에서는 13주)은 구조적으로 판정할 수 없다. 사후 판정 전용이다.
- **장점**: NBER식 경기순환 판정(Bry-Boschan 1971)과 같은 계보다. 낙폭과 기간을 모두 요구한다.
- **단점**: 파라미터가 5개이고 빈도에 민감하다. 반복 검열 절차가 복잡해서 사용자에게 설명하기 어렵다. 원 논문의 중요한 발견 하나는 "순수 랜덤워크도 실제와 비슷한 강세·약세 패턴을 만든다"는 것이다 [S02]. 국면이 있다는 사실 자체가 예측력을 뜻하지는 않는다.
- **사용처**: 학술 연구(Pagan, Harding & Pagan 계열), 각국 주가 사이클 비교.

### 2.2 통계적 국면 전환 모형

#### E. Hamilton (1989) 마르코프 국면 전환
- **정의**: 자기회귀 모형의 모수(평균 성장률 등)가 관측되지 않는 이산 마르코프 상태에 따라 바뀐다고 본다. 최우추정으로 각 시점이 어느 상태일 확률을 추론한다. 원 논문은 미국 실질 GNP에 적용해 경기침체를 객관적으로 정의할 수 있다고 제안했다 [S08].
- **무료 산출물**: FRED `RECPROUSM156N`(Chauvet-Piger 평활 침체확률)은 동적요인 마르코프 전환 모형에 4개 동행지표(비농업고용, 산업생산, 이전소득 제외 실질개인소득, 실질 제조·판매)를 넣어 매월 갱신된다. 약 1개월 뒤에 발표되고 값이 개정된다 [S16].
- **시점 문제**: "평활(smoothed)" 확률은 미래 관측까지 사용한다. 실시간 판단은 "필터링" 확률로만 할 수 있다. 재추정하면 과거 값도 바뀐다.
- **장점**: 평균과 변동성을 함께 쓰므로 전환을 더 빨리 포착한다. 예측에 강하다 [S04].
- **단점**: 상태 수, 분포 가정, 초기값에 따라 결과가 달라진다. 상태에 의미를 붙이는 작업은 사후 해석이다.

#### F. Ang & Bekaert (2002) — 국제 주식 국면
- **정의**: 미국·영국·독일 주식수익률에 국면 전환 모형을 적용했다. 그 결과 평균이 낮고 변동성과 상관관계가 높은 "고변동 국면"이 존재함을 보였다 [S10].
- **시사점**: 약세 국면에서는 분산 효과가 줄어든다. 다만 저자들은 국면을 무시해도 중간 수준의 위험회피 투자자에게는 비용이 작다고 보고했다. 국면 정보의 경제적 가치는 생각보다 작을 수 있다는 뜻이다.

#### G. Kritzman, Page & Turkington (2012) — 동인(driver) 기반 국면
- **정의**: 자산수익률 대신 **수익률의 동인**에 2상태 마르코프 모형을 각각 적용한다. 동인은 시장 난류(turbulence), 인플레이션, 경제성장이다. 예측된 국면에 따라 자산배분을 바꾼다 [S11]. FAJ 68(3)에 실렸고 정오표가 있다.
- **난류 지수** (Kritzman & Li 2010 [S12]): `d_t = (r_t − μ)ᵀ Σ⁻¹ (r_t − μ)`. 여러 자산 수익률 벡터의 마할라노비스 거리이며, 극단적 움직임과 상관관계 붕괴를 함께 잡는다.
- **데이터**: 다자산 일별 수익률(주식·채권·통화·원자재)과 μ·Σ 추정 창이 필요하다. 이 앱이 이미 모으는 시계열(지수·금리·환율·금·유가)로 근사할 수 있지만, 자산 구성에 따라 값이 달라진다.
- **시점 문제**: μ·Σ를 과거 창으로만 추정하면 실시간으로 계산할 수 있다. 전체 표본으로 추정하면 사후값이 된다.
- **사용처**: State Street Associates/Windham Capital(실무). 위험관리 지표로 널리 인용된다.

#### H. Two Sigma (2021) — 요인 수익률 GMM
- **정의**: Two Sigma Factor Lens의 미국 요인 17개(1970년대 초부터)에 가우시안 혼합모형을 적용해 4개 국면으로 나눈다. 국면은 Crisis(위기), Steady State(정상), Inflation(인플레이션), Walking on Ice(취약)다 [S09].
- **한계(저자 명시)**: 예측 모형이 아니다. 각 시점을 독립적으로 분류하므로 시간 순서를 고려하지 않는다. 1970~80년대 인플레이션 국면이 지금의 인플레이션과 같은 구조라는 보장도 없다.
- **이 앱에 대한 함의**: 요인 데이터를 무료로 구하기 어렵다. Fama-French 요인은 무료지만 Two Sigma의 17요인과는 다르다. 비교 실험 이상으로 쓰기 어렵다.

### 2.3 거시·경기순환 국면

#### I. NBER 경기순환 판정 (`USREC`)
- **정의**: NBER 경기순환판정위원회가 여러 지표를 보고 경기 고점과 저점을 판단한다. 고정된 수식은 없다 [S14].
- **시점 문제**: 고점은 평균 7.8개월, 저점은 평균 15.8개월 뒤에 발표된다. 범위는 4~21개월이다. 2007년 12월 고점은 12개월 뒤, 2020년 2월 고점은 4개월 뒤에 발표됐다 [S14]. 과거 음영으로는 표준이지만, 실시간 신호로 쓸 수 없다.
- **데이터**: FRED `USREC`(월간, 무료).

#### J. 실시간 침체 신호
- **Sahm 규칙**: 실업률 3개월 이동평균이 직전 12개월 중 3개월 평균의 최저치보다 0.50%p 이상 오르면 침체 신호다. FRED `SAHMREALTIME`은 처음 발표된 값(개정 전)으로 계산된다 [S17]. 1970년 이후 오신호가 없었지만, 2024년에 0.5를 넘은 뒤 침체 없이 되돌아갔다 [S17].
- **수익률곡선 프로빗(NY Fed)**: 10년물에서 3개월물을 뺀 금리차의 월평균으로 12개월 뒤 침체확률을 계산한다. 식은 `P = Φ(α + β·spread)`다 [S15]. 공개 문헌에 인용되는 계수는 α=−0.5333, β=−0.6629이며 1959~1995년 표본으로 추정됐다. 계수는 원문 FAQ에서 직접 확인하지 못했다. 1950년 이후 오신호는 1967년 한 번뿐이었다 [S15]. 그러나 2022년 7월~2024년 8월의 최장 역전 이후에도 2026년 초까지 NBER 침체는 판정되지 않았다 [S18].
- **함의**: 실시간 신호는 오신호가 생긴다. 표시할 때는 "신호"와 "확정 국면"을 다른 색과 다른 층으로 구분한다.

#### K. 성장×물가 4분면
- **Merrill Lynch Investment Clock (Greetham & Hartnett, 2004)** [S19]: 성장은 OECD 산출갭의 방향, 물가는 CPI 인플레이션의 방향으로 본다. 이 두 방향으로 4개 국면을 만들고, 1973~2004년 미국 데이터로 검증했다.

  | 국면 | 성장(산출갭) | 물가 | 최적 자산 |
  |---|---|---|---|
  | Reflation | 하강 | 하락 | 채권 |
  | Recovery | 상승 | 하락 | 주식 |
  | Overheat | 상승 | 상승 | 원자재 |
  | Stagflation | 하강 | 상승 | 현금 |

  원문도 "시계가 거꾸로 가거나 국면을 건너뛰기도 한다"고 인정한다. 산출갭 추정치는 사후에 크게 개정된다.
- **Bridgewater All Weather** [S20]: 성장 상승, 성장 하락, 물가 상승, 물가 하락의 네 환경을 **시장 기대 대비 서프라이즈**로 정의한다. Bridgewater는 다음 환경을 예측하지 않는다고 명시하고, 네 환경에 위험을 균형 배분한다. 기대치(컨센서스) 데이터가 필요하므로 무료 데이터로는 재현하기 어렵다. 실현값의 방향으로 바꾸면 Investment Clock과 같은 구조가 된다.
- **Fidelity 경기순환 접근** [S21]: 초기, 중기, 후기, 침체의 4단계로 나눈다. GDP·산업생산의 변곡, 신용 여건, 통화정책, 재고, 이익률 등 여러 지표를 종합해 사람이 판단한다. 기계적 규칙이 아니므로 그대로 재현할 수 없다.
- **선행지수**: Conference Board LEI는 유료 라이선스다. FRED의 필라델피아 연준 `USSLIND`는 2020년 2월에 중단됐다 [S22]. OECD CLI(`USALOLITOAASTSAM`)는 FRED에서 무료로 받을 수 있지만 2023년 9월에 방법론이 바뀌면서 과거 값이 개정됐다 [S23]. 국면 경계를 정하는 입력으로는 개정 위험이 크다.

### 2.4 추세 기반

#### L. Faber (2007) 10개월 이동평균
- **규칙** [S24]: 매월 마지막 거래일 종가가 10개월 단순이동평균보다 높으면 보유하고, 낮으면 현금(T-bill)으로 바꾼다. 월중 변동은 무시한다. 총수익 지수를 쓰고 세금·거래비용은 제외한다.
- **결과(S&P 500, 1901~2012)**: 연복리수익률은 타이밍 10.18%, 보유 9.32%였다. 약 70%의 기간에 투자 상태였고, 왕복 매매는 연 1회 미만이었다. 1929~32년 최대낙폭은 83.66%에서 42.24%로 줄었다. 대신 절반 가까운 해에 지수보다 뒤처졌다 [S24].
- **시점 문제**: 월말 종가만으로 계산하므로 **실시간으로 알 수 있는 유일한 가격 국면**이다. 대신 휩쏘(잦은 신호 번복)가 생긴다.
- **200일 이동평균**: 일간판이며 Faber가 월간 등가물로 제시한 기준이다 [S24]. 신호가 더 자주 바뀐다.
- **다우 이론**: 다우 산업지수와 운송지수가 서로 확인해야 추세로 인정한다. 고점·저점의 판정이 해석에 의존하므로 결정론적 규칙으로 만들기 어렵다 [S25].

### 2.5 밸류에이션·신용 국면

- **신용스프레드**: FRED의 ICE BofA OAS(HY·BBB·AAA)는 라이선스 때문에 최근 3년치만 제공된다 [S26]. 장기 대안은 Moody's `BAA`·`AAA` 수익률(월간, 장기 시계열)에서 국채 10년물(`GS10`)을 빼서 만든다. 일간 `BAA10Y`는 1986년부터 있다. 연준 이사회가 매월 갱신하는 **Gilchrist-Zakrajšek 초과채권프리미엄(EBP)**은 1973년부터 CSV로 무료 공개된다 [S27]. EBP는 스프레드에서 기대부도로 설명되지 않는 부분, 곧 위험선호를 뜻한다.
- **수익률곡선 역전**: 10년물−3개월물이 NY Fed 모형의 기준이고 [S15], 10년물−2년물은 시장 관행이다. 역전에서 침체까지의 지연이 길고 가변적이다(수개월~2년). 2022~24년 사례가 있으므로 "역전 = 침체 예고"로 단정하면 안 된다 [S18].
- **Shiller CAPE**: 1871년부터의 월간 S&P 가격·배당·이익·CPI 데이터가 Yale에서 무료로 공개된다 [S28]. 국면 분류보다는 장기 기대수익의 배경 변수다. 단기 국면 판단에는 쓰지 않는다.

---

## 03 / 근거 비교 — 무엇을 뒷받침하고, 어디까지 말할 수 있나

| 방법 | 결정론 | 설명 용이 | 실시간 여부 | 무료 데이터 | 이 앱 적합도 |
|---|---|---|---|---|---|
| −20% 종가 규칙 | ✓ | 매우 쉬움 | 사후(확인일은 실시간) | ✓ `^GSPC` 1927~ | **주 층** |
| Lunde-Timmermann | ✓ | 쉬움 | 사후, 지연 큼 | ✓ | 주 층(일반형) |
| Pagan-Sossounov | ✓ | 어려움 | 사후, 끝 6개월 판정 불가 | ✓ | 견고성 점검용 |
| Ned Davis | ✓ | 보통 | 사후 | ✓(DJIA) | 선택 |
| Hamilton/HMM | 추정 의존 | 어려움 | 필터확률만 실시간, 재추정 시 과거 변경 | ✓ | 비교 실험 |
| GMM(Two Sigma) | 추정 의존 | 어려움 | 시간 무시, 비예측 | ✗(요인 데이터) | 제외 |
| 난류 지수 | ✓(창 고정 시) | 보통 | ✓(롤링 추정) | 부분 | 오버레이 후보 |
| NBER `USREC` | 위원회 판단 | 쉬움 | 사후 4~21개월 | ✓ | **거시 주 층** |
| Sahm 실시간 | ✓ | 쉬움 | ✓(초판값) | ✓ | 신호 오버레이 |
| 곡선 프로빗 | ✓ | 보통 | ✓ | ✓ | 신호 오버레이 |
| 성장×물가 4분면 | ✓(정의 고정 시) | 보통 | 발표 1개월 지연, 개정됨 | ✓(INDPRO·CPI) | 2단계 |
| Faber 10M SMA | ✓ | 매우 쉬움 | ✓ | ✓ | **실시간 추세 층** |

해석의 경계:
- **국면 식별과 국면 예측은 다른 주장이다** [S04]. 이 앱의 타임라인은 식별이다. 국면 라벨을 매매 신호처럼 쓰면 안 된다.
- 랜덤워크도 강세·약세 패턴을 만든다 [S02]. "약세장마다 X가 일어났다"는 표본 수가 작은 관찰이다. 미국 S&P 500 기준으로 1928년 이후 −20% 약세장은 20여 회, 1980년 이후는 6~7회뿐이다.
- 실시간 신호(Sahm, 곡선)는 2020년대에 오신호를 냈다 [S17][S18]. 과거의 적중률이 구조 변화 뒤에도 유지된다고 보장할 수 없다.

---

## 04 / 버크셔 해서웨이와 하락장 — 공개 근거

| 근거 | 내용 | 해석의 경계 |
|---|---|---|
| Frazzini·Kabiller·Pedersen, *Buffett's Alpha* (FAJ 2018) [S29] | 1976.10~2017.3 기준 BRK의 연 초과수익률 18.6%(시장 7.5%), 변동성 23.5%(시장 15.3%), 샤프 0.79(시장 0.49), **시장 베타 0.69**, 평균 레버리지 약 1.7배. BAB(저베타)·QMJ(퀄리티) 요인을 통제하면 알파가 유의하지 않게 됨 | BRK의 하락장 방어는 상당 부분 **저베타·퀄리티 노출의 기계적 결과**다. 하락장 초과수익을 "운용 능력"으로 해석하려면 베타 조정이 필요하다 |
| 같은 논문 | 1998.6.30~2000.2.29 동안 BRK −44%, 시장 +32%(76%p 열위) | 투기적 강세장 후반에는 크게 진다. "약세장에서 이긴다"의 거울상이다 |
| 버크셔 주주서한 연간 표(Motley Fool 2026 정리) [S30] | 1965년 이후 S&P 500(배당 포함)이 하락한 13개 연도 중 11개 연도에 BRK가 앞섬. 예외는 1974(BRK −48.7% vs −26.4%)와 1990(−23.1% vs −3.1%). 2000 +26.6% vs −9.1%, 2001 +6.5% vs −11.9%, 2002 −3.8% vs −22.1%, 2008 −31.8% vs −37.0%, 2022 +4.0% vs −18.1% | 달력연도 단위라 국면 경계와 맞지 않는다. 2차 정리 자료이므로 원 표(주주서한)로 재확인이 필요하다 |
| CNBC(2023) [S31] | 1980년 이후 S&P 500이 20% 하락한 모든 경우에 BRK가 앞섬(중앙값 +14.89%p). 6번의 침체에서 중앙값 +4.41%p | 본문 접근이 차단되어(403) 검색 요약으로만 확인. 계산 방식은 미확인 |

종합하면, 가설에는 공개 근거가 있다. 다만 (1) 저베타 효과, (2) 1974·1990 같은 예외, (3) 1998~2000 강세장 후반의 큰 열위를 함께 보여 줘야 정직한 비교가 된다.

---

## 05 / Explorer 적용 — 권장 설계

### 5.1 구조: 3개 층과 오버레이

```
층 A  시장 국면 (가격)   ── 사후 확정 국면 + 확인일     ← 버크셔 질문의 주 축
층 A' 실시간 추세        ── 10개월 SMA 위/아래          ← "그때 알 수 있었던 것"
층 B  경기 국면 (거시)   ── NBER 침체 음영 (+ 2단계: 성장×물가 4분면)
오버레이(연속 시계열)    ── 금리차·신용스프레드·EBP·VIX·환율 + 임계선
```

층마다 판정 성격(사후/실시간)을 배지로 표시한다. 오버레이는 국면을 판정하지 않고 사용자가 직접 겹쳐 보는 재료로만 쓴다.

### 5.2 층 A — 시장 국면 (P0)

- **대상**: S&P 500 `^GSPC` 일별 종가(1927-12-30~)를 기본으로 한다. 같은 함수를 `^IXIC`(1971~), KOSPI에도 적용할 수 있게 지수 파라미터만 바꾼다.
- **알고리즘**: Lunde-Timmermann 필터를 **대칭 20/20**으로 쓴다.
  - 강세 상태에서 직전 저점 이후 최고 종가 대비 하락률이 **20% 이상**이면, 그 최고점을 `peak`로 확정한다. 이 조건을 처음 만족한 날이 `confirm_date`다.
  - 약세 상태에서 직전 고점 이후 최저 종가 대비 상승률이 **20% 이상**이면, 그 최저점을 `trough`로 확정한다.
  - 강세 구간은 trough+1~peak, 약세 구간은 peak+1~trough로 둔다.
  - 20/20을 고른 이유: S&P DJI·Yardeni 공개 표와 대조해 검증할 수 있다. 원 논문의 15%(→약세)는 민감도 옵션으로 제공한다.
- **보조 라벨(국면이 아닌 주석)**: 강세 구간 안에서 직전 최고 종가 대비 낙폭이 **10~20% 미만**인 구간을 `조정`으로 표시한다. 낙폭이 **18% 이상**이면 `임계 근접`으로 강조한다(1990·2011·2018이 여기에 해당). 조정의 시작은 낙폭 ≥10%가 된 구간의 고점이고, 끝은 직전 고점을 회복한 날이다.
- **진행 중 국면**: 마지막 전환 이후 구간은 `잠정`으로 표시한다. 현재 고점 대비 낙폭과 현재 저점 대비 반등률을 함께 보여 준다.
- **저장 스키마(제안)**: `market_phase(index, phase, start_date, end_date, peak_or_trough_close, confirm_date, change_pct, is_provisional, params_version)`. 파라미터를 바꾸면 버전을 올려 다시 계산한다.
- **검증**: 1928년 이후 S&P 500 약세장 목록을 Yardeni 표 [S06]와 대조한다. 종가 기준 차이(장중 기준과의 차이) 때문에 생기는 불일치는 문서화한다.
- **견고성 점검(P2)**: Pagan-Sossounov(월간 8/6/4/16/20%)로 다시 계산해 국면 경계 일치율을 보고한다.

### 5.3 층 A' — 실시간 추세 (P0)

- 월말 종가가 10개월 SMA보다 높으면 `상승추세`, 낮으면 `하락추세`로 표시한다(Faber 규칙 그대로) [S24]. 월말에만 바뀐다.
- 목적: 층 A의 사후 국면과 나란히 보여 주어 "약세장 한복판이라고 지금은 말하지만, 당시 실시간 신호는 언제 바뀌었나"를 드러낸다. 매매 성과는 주장하지 않는다.

### 5.4 층 B — 경기 국면

- **P0**: FRED `USREC`로 침체 음영을 그린다. 툴팁에 "NBER 사후 판정, 발표 지연 4~21개월"을 고정 문구로 넣는다 [S14].
- **P1 신호 오버레이**: `SAHMREALTIME` ≥ 0.50, 10년−3개월 금리차 < 0(월평균; `T10Y3M` 일간은 1982년부터, 그 이전은 `GS10`−`TB3MS` 월간)을 신호로 표시한다. 둘 다 오신호 사례를 툴팁에 적는다.
- **P2 성장×물가 4분면**(Investment Clock의 무료 근사):
  - 성장: `INDPRO` 전년비 증가율의 6개월 변화 부호(+ 가속, − 감속)
  - 물가: `CPIAUCSL` 전년비 상승률의 6개월 변화 부호
  - 4분면 이름: Recovery(성장↑ 물가↓), Overheat(↑↑), Stagflation(성장↓ 물가↑), Reflation(↓↓)
  - 휩쏘 완화: 같은 분면이 **2개월 연속**일 때만 전환한다.
  - 한계: 발표 지연이 1개월이고 INDPRO는 개정된다. 실시간 판정을 재현하려면 ALFRED 빈티지 데이터가 필요하다. 산출갭을 쓰는 원판과 같지 않다고 명시한다.

### 5.5 오버레이 — 연속 시계열 (P0~P1)

신용은 Baa−10Y(월간 `BAA`−`GS10`으로 장기 시계열을 만들고, 1986년 이후는 일간 `BAA10Y`), EBP(연준 CSV, 1973~) [S27]를 쓴다. 금리는 2Y·10Y·커브, 그 밖에 VIX, USD/KRW, WTI, 금을 넣는다. ICE BofA OAS는 3년치만 있으므로 장기 비교에서 뺀다 [S26]. 난류 지수(롤링 3년 μ·Σ, 주식·채권·달러·금·유가 일간수익률)는 P2 실험으로 둔다.

### 5.6 버크셔 질문의 계산 규칙

1. **가격 데이터**: `BRK-A` 일간(1980-03-17~)을 쓴다. `BRK-B`(1996-05~)보다 16년 길다. yfinance에서 `interval='1mo'`로 받으면 1985년부터만 반환되므로, 일간으로 받아 직접 월말 리샘플링한다(2026-10 확인).
2. **벤치마크는 총수익**: 1988년 이후는 `^SP500TR`을 쓴다. 1980~87년은 Shiller 월간 배당 데이터로 총수익을 근사한다 [S28]. 근사 구간은 표시한다. `^GSPC` 가격지수와 비교하면 BRK가 유리해지는 편향이 생긴다.
3. **주 지표 — 국면별 초과수익**: 층 A의 각 강세·약세 구간에 대해 `BRK 구간수익률 − S&P 500 TR 구간수익률`을 계산한다. 12개월 롤링 창은 국면 경계를 걸치므로, 가설 검정에는 **국면 구간 단위 수익률**이 더 깨끗하다.
4. **보조 지표 — 롤링 12개월 초과수익 그래프**: 월말 기준 12개월 초과수익을 선으로 그리고, 배경에 층 A 국면 색을 깐다. 겹치는 창은 서로 독립적이지 않으므로 "몇 % 기간에 이겼다" 같은 빈도 통계는 비중복 창으로만 계산한다.
5. **베타 조정선**: 직전 36개월 롤링 베타 β로 `BRK − β·S&P`도 함께 보여 준다. 저베타 효과와 그 밖의 효과를 나눠 보려는 것이다 [S29].
6. **표본 크기 명시**: 1980년 이후 약세장은 1987, 2000~02, 2007~09, 2020, 2022 정도이고, 1990은 임계 근접이다. "n=5~6"이라고 화면에 쓴다.

### 5.7 하지 않을 것

- HMM·GMM 결과를 국면 라벨로 쓰지 않는다(재추정 시 과거 변경, 설명 불가).
- Bridgewater식 "기대 대비 서프라이즈" 분면은 쓰지 않는다(컨센서스 데이터 없음).
- Fidelity식 4단계는 재현하지 않는다(재량 판단).
- LLM이 국면을 판정하지 않는다. 모든 라벨은 위 규칙과 파라미터 버전으로 다시 계산할 수 있어야 한다.

---

## 06 / 조사 기준과 한계

- 학술 원문(가능하면 PDF 본문)과 공식 방법론 페이지를 우선했다. 원문 접근이 막힌 자료(CNBC, SSRN 초록 일부)는 검색 요약으로 확인했다는 사실을 표에 적었다.
- NY Fed 프로빗 계수(α=−0.5333, β=−0.6629)는 2차 출처의 인용값이다. NY Fed FAQ 원문에서는 함수 형태와 변수 정의만 확인했다.
- Merrill Lynch Investment Clock 원문의 정확한 평활 방식(산출갭 방향 판정 기간)은 확인하지 못했다. 5.4의 6개월 변화 규칙은 이 앱을 위한 제안이다.
- `^GSPC` 1927~1957년 구간은 S&P 90 등 이전 지수를 이어 붙인 값이다. 초기 약세장의 수치는 다른 자료와 조금 다를 수 있다.
- 2026년 이후 NBER 판정이나 지표 개정은 반영하지 않았다.

---

## 출처

**강세·약세 판정**
- [S02] Pagan, A. & Sossounov, K. (2003). A simple framework for analysing bull and bear markets. *Journal of Applied Econometrics* 18(1), 23–46. https://onlinelibrary.wiley.com/doi/abs/10.1002/jae.664 · 공개본 https://eprints.qut.edu.au/8045/
- [S03] Zakamulin, V. Introduction to the bbdetection package (LT·Bry-Boschan 구현, PS 파라미터 정리). https://vzakamulin.weebly.com/uploads/4/2/4/2/42424487/introduction_to_the_bbdetection_package.pdf · Lunde & Timmermann (2004), *JBES* 22(3), 253–273. https://ideas.repec.org/a/bes/jnlbes/v22y2004p253-273.html
- [S04] Kole, E. & van Dijk, D. (2013). How to Identify and Forecast Bull and Bear Markets? Erasmus Research Institute. https://repub.eur.nl/pub/41558/ERS-2013-016-F&A.pdf
- [S05] CNBC (2022-06-13). The S&P 500 is now in an official bear market, according to S&P Dow Jones Indices. https://www.cnbc.com/2022/06/13/sp-500-is-in-official-bear-market-according-to-sp-dow-jones-indices.html
- [S06] Yardeni Research. S&P 500 Bull & Bear Markets & Corrections. https://archive.yardeni.com/pub/sp500corrbeartables.pdf · https://yardeni.com/charts/us-stock-market/stock-market-historical-trends/bull-bear-markets-corrections
- [S07] Stock Trader's Almanac — Ned Davis Research 정의. https://jeffhirsch.tumblr.com/post/137748126213/its-an-official-ned-davis-research-defined-bear

**통계적 국면 모형**
- [S08] Hamilton, J. D. (1989). A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle. *Econometrica* 57(2), 357–384. https://www.econometricsociety.org/publications/econometrica/1989/03/01/new-approach-economic-analysis-nonstationary-time-series-and
- [S09] Botte, A. & Bao, D. (2021). A Machine Learning Approach to Regime Modeling. Two Sigma. https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/
- [S10] Ang, A. & Bekaert, G. (2002). International Asset Allocation With Regime Shifts. *Review of Financial Studies* 15(4), 1137–1187. https://econpapers.repec.org/RePEc:oup:rfinst:v:15:y:2002:i:4:p:1137-1187 · 개관: Ang & Timmermann, Regime Changes and Financial Markets. https://www.netspar.nl/wp-content/uploads/068_Ang.pdf
- [S11] Kritzman, M., Page, S. & Turkington, D. (2012). Regime Shifts: Implications for Dynamic Strategies. *FAJ* 68(3). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2066848 · 정오표 https://www.tandfonline.com/doi/full/10.2469/faj.v68.n5.9
- [S12] Kritzman, M. & Li, Y. (2010). Skulls, Financial Turbulence, and Risk Management. *FAJ* 66(5). https://www.top1000funds.com/wp-content/uploads/2010/11/FAJskulls.pdf

**경기순환·거시**
- [S14] NBER Business Cycle Dating / FAQ. https://www.nber.org/research/business-cycle-dating · https://www.nber.org/research/business-cycle-dating/business-cycle-dating-procedure-frequently-asked-questions · FRED Blog, Dating a recession. https://fred.stlouisfed.org/blog/2020/06/dating-a-recession/
- [S15] Federal Reserve Bank of New York. The Yield Curve as a Leading Indicator: FAQ. https://www.newyorkfed.org/medialibrary/media/research/capital_markets/ycfaq.pdf · Estrella & Mishkin, The Yield Curve as a Predictor of U.S. Recessions. https://www.newyorkfed.org/research/current_issues/ci2-7.html
- [S16] FRED, Smoothed U.S. Recession Probabilities (RECPROUSM156N). https://fred.stlouisfed.org/series/RECPROUSM156N
- [S17] FRED, Real-time Sahm Rule Recession Indicator (SAHMREALTIME). https://fred.stlouisfed.org/series/SAHMREALTIME · 2024 신호 정리: https://eco3min.fr/en/sahm-rule-false-signals-history/
- [S18] 2022–24 수익률곡선 역전과 침체 미판정 정리(2차 자료). https://eco3min.fr/en/yield-curve-inversion-history-2s10s-spread/ · https://www.lambdafin.com/articles/yield-curve-inversion-recession-lead-time
- [S19] Greetham, T. & Hartnett, M. (2004). The Investment Clock. Merrill Lynch. https://silo.tips/download/the-investment-clock
- [S20] Bridgewater. The All Weather Story. https://www.bridgewater.com/research-and-insights/the-all-weather-story
- [S21] Fidelity. The Business Cycle Approach to Equity Sector Investing. https://www.fidelity.com/webcontent/ap101883-markets_sectors-content/21.01.0/business_cycle/Business_Cycle_Sector_Approach_2020.pdf
- [S22] FRED, Leading Index for the United States (USSLIND, 2020-02 종료). https://fred.stlouisfed.org/data/USSLIND · Conference Board LEI. https://www.conference-board.org/topics/us-leading-indicators/
- [S23] ALFRED, OECD CLI Amplitude Adjusted for United States (USALOLITOAASTSAM) 빈티지 이력. https://alfred.stlouisfed.org/series?seid=USALOLITOAASTSAM

**추세·밸류에이션·신용**
- [S24] Faber, M. (2007, 2013 개정). A Quantitative Approach to Tactical Asset Allocation. *Journal of Wealth Management*. https://www.cambriainvestments.com/wp-content/uploads/2018/01/A-Quantitative-Approach-to-Tactical-Asset-Allocation.pdf
- [S25] Market trend / Dow theory 개관. https://en.wikipedia.org/wiki/Market_trend
- [S26] FRED, ICE BofA US High Yield Index OAS (3년 제한 공지). https://fred.stlouisfed.org/series/BAMLH0A0HYM2
- [S27] Favara, Gilchrist, Lewis & Zakrajšek, Updating the Recession Risk and the Excess Bond Premium (FEDS Notes, 매월 갱신). https://ideas.repec.org/p/fip/fedgfn/2016-10-06.html · 데이터 https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv
- [S28] Shiller, R. Online Data (ie_data.xls). http://www.econ.yale.edu/~shiller/data.htm

**버크셔 해서웨이**
- [S29] Frazzini, A., Kabiller, D. & Pedersen, L. H. (2018). Buffett's Alpha. *FAJ* 74(4), 35–55. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3197185 · NBER WP 19681 https://www.nber.org/papers/w19681
- [S30] Motley Fool (2026-10-15). History Says Berkshire Hathaway Stock Holds Up When the Market Falls. https://www.fool.com/investing/2026/10/15/history-says-berkshire-hathaway-stock-holds-up-whe/ · 원 자료: Berkshire Hathaway 연례 주주서한 성과표 https://www.berkshirehathaway.com/letters/letters.html
- [S31] CNBC (2023-05-05). Warren Buffett's Berkshire Hathaway has been a fortress stock during recessions and bear markets. https://www.cnbc.com/2023/05/05/warren-buffetts-berkshire-hathaway-has-been-a-fortress-stock-during-recessions-and-bear-markets-heres-how.html
