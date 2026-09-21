# 차트 구조 그리기 — 종목 하나의 채널·추세선 (2026-09-21, D-195)

"가온전선에 대해서, 올해 전고점들을 기반으로 큰 채널을 그려줘" 같은 요청은 조건으로 종목을 거르는 일이 아니라 **종목 하나의 차트에 구조를 그리는 일**이다. 종목 발견의 해석 모델은 이것을 "카탈로그 조건이 아님"으로 돌려 후보 0개를 냈다(2026-09-21 실사용). 이 문서는 그 요청을 결정적 계산으로 받아 그리는 계약이다. 가격 구조 전략(D-187, [market-strategies.md](market-strategies.md))의 스윙 검출·직선 적합을 재사용하고, 모델 호출은 0이다.

## 범위

- **P0**: 종목 1개(국내·미국), 구조 3종(채널 · 고점 추세선 · 저점 추세선), 기간(올해·3/6개월·1/2년·직접 날짜), 스윙 폭(잔파동 무시 정도), 적합 방식(두 점 연결 기본 · 회귀 옵션). 종목 발견 대화 안의 차트 카드 + 기업 페이지 기술적 분석 패널의 "구조 그리기". 질문 문장 → 매개변수 해석은 규칙 기반.
- **P1**: 수평 지지·저항 레벨, 여러 종목 비교, 그린 구조 → 감시 규칙(D-185) "상단 돌파 시 알림"·검색 조건 변환, 해석이 애매할 때 모델 보조.
- **Out of scope**: 이미지(PNG) 생성, 사용자가 손으로 선을 끄는 편집.

## 계산 (`backend/pipeline/chart_structure.py`)

입력: 일봉 rows(날짜 오름차순), `kind`, `window`, `swing`, `fit`.

- **스윙 점**: `strategies._pivot_indexes`와 같은 규칙 — 양쪽 `swing`개 봉보다 높은(낮은) 봉. 기간 안 봉만 본다. 마지막 `swing`개 봉은 스윙이 될 수 없다(오른쪽 확인 봉 부족).
- **채널**(`channel`): 상단선은 스윙 고점으로 적합. `two_point`는 **가장 높은 고점 두 개**를 잇는다(사람이 손으로 긋는 "전고점 연결"과 가장 비슷). `regression`은 모든 스윙 고점의 최소제곱선. 하단선은 상단선과 평행하게 기간 안 **가장 낮은 저가에 닿도록** 내린다.
- **고점 추세선**(`trendline_high`): P1 = 기간 최고 스윙 고점, P2 = P1 이후 가장 높은 스윙 고점(없으면 이전). 하락 저항선. `regression`은 전체 스윙 고점.
- **저점 추세선**(`trendline_low`): 대칭(최저 스윙 저점 → 이후 최저). 상승 지지선.
- **스윙 폭 자동 완화**: 요청 폭에서 스윙이 2개 미만이면 폭을 1씩 줄여 2개 이상이 되는 첫 폭을 쓰고 `notes`에 남긴다. 2까지 줄여도 없으면 422 "기간이 짧거나 변동이 작아 구조를 그릴 수 없습니다".
- **선은 두 끝점**으로 돌려준다(첫 기준점 봉 → 마지막 봉). lightweight-charts는 점 사이를 직선으로 잇는다.
- **요약**: 상·하단 현재값, 종가의 채널 내 위치(%), 기울기(세션당 %), 채널 폭(%), 상·하단 접촉 횟수(선에서 0.5% 이내 고가/저가).

## 해석 규칙 (`interpret(question)`)

그리기 요청 = **구조 단어**(채널 · 추세선 · 고점/저점 연결 · 지지선/저항선) **and 그리기 동사**(그려 · 그리 · 표시 · 보여 · 찍어) **and 종목 해소** **and 검색 동사 없음**(찾아 · 검색 · 골라 · 추려 · 종목들 · 조건). 셋 중 하나라도 빠지면 종목 발견의 조건 검색으로 간다(오탐이 나면 종목이 걸러지는 쪽으로 틀리는 게 낫다).

| 단서 | 값 |
|---|---|
| 채널 / 고점·저항·전고점 (+연결·선) / 저점·지지·전저점 (+연결·선) / 추세선 단독 | channel / trendline_high / trendline_low / trendline_low |
| 올해·연초·YTD / N개월 / N년 / 없음 | ytd / Nm / Ny / 1y |
| 큰·장기·주요·메이저 / 작은·단기·세밀 / 없음 | swing 10 / 3 / 5 |
| 회귀·평균·전체 고점 | fit regression (기본 two_point) |
| 종목 | 조사(에 대해서·의·은/는/을/를) 제거한 토큰을 `companies.corp_name` 정확·접두·포함 순으로 해소. 대문자 1~5자는 미국 티커(`resolve_us`) |

## API

- `GET /api/spine/chart-structure/{code}?market=kr|us&kind=channel|trendline_high|trendline_low&window=ytd|3m|6m|1y|2y|YYYY-MM-DD:YYYY-MM-DD&swing=2..30&fit=two_point|regression` → `{code,name,market,kind,fit,swing,requested_swing,window:{from,to,sessions},candles:[{time,open,high,low,close}],pivots:[{time,price,side}],lines:[{id,label,points:[{time,value}×2]}],summary,notes}`. candles는 기간 앞 20봉을 문맥으로 포함. 404 시세 없음, 422 그릴 수 없음.
- `POST /api/spine/chart-structure/interpret` `{question}` → `{draw:true, code,name,market,kind,window,swing,fit, matched:[…단서]}` 또는 `{draw:false, reason}`. 모델 호출 0.

## 화면

공용 카드 `components/structure/ChartStructureCard.tsx`(shared 조합: CandlestickChart + ToggleGroup·Select·Slider). 종목 발견은 `?mode=draw&code&market&kind&window&swing&fit&q`로 URL에 상태를 두고 카드를 대화의 한 턴처럼 올린다. 기업 페이지 기술적 분석 패널의 "구조 그리기" Collapsible이 같은 카드를 연다.

| 상태 | 표시 |
|---|---|
| Empty | 종목 발견: 질문이 그리기로 해석됐지만 종목을 못 찾음 → "어느 종목인지 적어주세요" + 조건 검색으로 보내기 버튼 |
| Loading | 차트 자리 Skeleton + "스윙 점을 찾고 있습니다" |
| Partial | 스윙 폭이 자동 완화됨(notes 배지), 기간 앞이 시세 시작으로 잘림 |
| Error | 422 사유 그대로 + 스윙 폭 줄이기·기간 늘리기 버튼, 그 외 ErrorState 재시도 |
| Ideal | 캔들 + 상·하단선(파선) + 스윙 점 마커 + 요약 한 줄(위치 %·기울기·접촉) + 컨트롤 + "기업 페이지에서 보기"/"이 종목 조건 검색" 링크 |

캡션: "구조는 규칙(스윙 폭·적합 방식)으로 그린 결정적 선이고 예측이 아닙니다."

## 검증

`backend/tests/test_chart_structure.py`: 합성 채널 시계열에서 두 최고점 연결·하단 접촉·위치 %, 스윙 폭 자동 완화, 그릴 수 없음 422, 해석 규칙(가온전선 문장 → channel/ytd/10, 검색 동사 포함 문장 → draw:false, 미국 티커). 실사용: 가온전선(000500) 올해 채널을 브라우저에서 확인.
