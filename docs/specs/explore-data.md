# 탐색 › 수출입·회사채·인물·기업활동 — 변화를 앞에 보이기

- 상태: P6b 구현 계약 (2026-10-16). 셸은 [app-shell](app-shell.md), 위젯 계약은 [home-widgets](home-widgets.md) §2.
- 수출입 원천·판정은 [trade-follow](trade-follow.md), 회사채 계산은 [credit-spreads](credit-spreads.md), 인물 프로필 생성 규율은 [source-dossier](source-dossier.md)를 따른다.
- 원칙: 서버가 이미 계산한 변화(판정·Δ·정정 여부)를 첫 화면 정렬과 배지로 쓴다. 새 LLM 호출·cron은 없다.

## 1. 수출입 `/follow/trade`

- 레일 기본 정렬 = 이번 달 기여도(전년 동월 대비 증감액 |Δ| / 최상위 품목 Σ|Δ|) 내림차순. `?trade_sort=group`이면 분류별(분류는 최상위 품목 금액 합 순).
- 행: 품목명 · 판정 배지(급등·급감·신규, `flag`) · 금액·YoY. 배지 툴팁 = 서버 `reason`·기여도·판정 기준. 하위 세목이면 '…의 세목'.
- 머리: 통계월 · 팔로우 수 · 급등·급감 수(`flag=surge`·`plunge`).
- 데이터 위생(`pipeline/trade.py` `normalize_labels`, 시드 직후마다 멱등):
  - 알려진 오기는 HS로 고정한다(`HS_LABEL_FIX`: 8542321010 '총수출'·전자부품 → 'D램'·반도체).
  - 'OLDE' → 'OLED', 끝의 '(2)' 같은 번호 접미를 뗀다. 떼고 나서 이름이 겹치면 `이름 · HS`로 구분한다.
- 이중 집계(`trade_metrics.nesting`): 팔로우 HS가 다른 팔로우 HS의 접두사면 하위 행에 `nested_in`=가장 가까운 상위 HS. 관세청은 상위 부호 조회에 하위 세목을 합산해 돌려주므로 하위 행은 수출 합계(`total_usd`)·기여도 분모에서 뺀다. 분류 합계는 같은 분류 안에 상위가 있을 때만 뺀다.
- 종목 → 품목: `GET /api/spine/trade/by-stock/{code}` = `trade_beneficiaries`에서 이 종목을 지목한 품목 + 이번 달 판정(읽기 전용).

## 2. 회사채 `/follow/credit`

- 표 기본 정렬 = 1개월 스프레드 변화 내림차순(확대가 위). `?credit_sort=spread|group`. 한 줄 순위에서는 묶음 이름을 회사 옆에 보인다.
- 차트 기본 선택 = 1개월 확대 상위 2곳(`?credit=`가 있으면 그것).
- 머리 한 줄: '1개월 새 가장 벌어진 곳' 상위 3 + HY 수. 원천이 설정되고 수집분이 있을 때만.

## 3. 인물 `/people`, `/person`

- `GET /api/spine/person` → `{items, total, hidden_tail, as_of}`.
  - 집계는 쿼리 3번이다: 언급 수·7일·직전 7일, 최근 문서(창 함수), 함께 언급된 종목 상위 3(창 함수). 인물마다 서브쿼리를 돌던 N+1을 대체했다.
  - `sort=surge`(기본, `delta_7d` = 최근 7일 − 직전 7일) | `total` | `recent`.
  - `min_mentions=2`(기본): 언급 1건 인물은 숨긴다. 팔로우 인물은 늘 보인다.
  - `days`는 집계 안의 창이다. 7일 Δ는 창 밖도 본다. 게시 시각은 `datetime()`으로 정규화해 비교한다.
- 화면: 정렬 토글(`?sort=`) · '언급 1건도 보기' 스위치(`?tail=1`) · 행마다 7일 언급(Δ)·누적 · 100명씩 더 보기. 최근 문서는 '최근 언급'이다. 문서가 발화인지 언급인지는 구분하지 않는다.
- 도시에 `GET /{name}/dossier`에 두 필드를 더했다.
  - `relations`: `entity_relations`에서 이 인물이 src·dst인 엣지 최신 20개. 필드는 방향·상대·메커니즘·가설 여부, 그리고 출처 내러티브 주제의 현행 버전 제목과 `narrative_superseded`다.
  - `new_since_profile`: 프로필 생성 이후 수집(`fetched_at`)된 언급 수.
- '등장하는 내러티브·인과 엣지' 카드: 주제 칩(→ `/narrative?topic=`)과 엣지 목록을 보인다. 엣지가 없으면 카드를 그리지 않는다.
- 프로필 머리에 '프로필 이후 새 언급 N건'과 '다시 만들기'(기존 `POST /{name}/profile`)를 둔다. 열람 시 생성 규율은 그대로 두고, 자동·예약 재생성은 더하지 않았다.

## 4. 기업활동 `/actions`

- `GET /api/spine/actions`에 다음을 더했다.
  - `kind=all|original|correction`(API 기본 all). `report_nm`에 '정정'이 있으면 정정이다.
  - `stock_code` 필터.
  - `counts{original, correction}`: kind 필터를 걸기 전 수.
  - 항목별 `is_correction`·`my_group`('보유'=portfolio 묶음 우선, '관심'=watch 묶음, `stock_groups` 기준).
- `/actions/rights` 행에도 `my_group`이 있다.
- 화면: 원공시(기본)·정정·전체 토글(`?kind=`) · 내 종목은 맨 위에 고정하고 배지를 단다 · 정정 행에는 '정정' 배지.
- 국내 도시에 개요의 '최근 활동' 줄(`summary/StockActivityStrip`)은 두 가지를 보인다.
  - 최근 30일 기업활동: 원공시 칩과 정정 수. `stock_brief`와 같은 30일 창이며 `/actions?stock_code=`로 읽는다.
  - 수출 지표: 이 종목을 지목한 품목 칩.
  - 둘 다 없으면 줄을 그리지 않는다.

## 5. 위젯 5종 (탐색 섹션, `widgets/exploreFollow.tsx`)

| id | 이름 | 원천 | 기본 크기 | 머리 시각(원천 리듬) · 고장 | 큰 숫자 · 한 줄 · 목록 |
|---|---|---|---|---|---|
| explore.trade | Trade Pulse | `/trade/highlights?limit=5` | 4×4 | 통계월 · 2개월 넘게 묵음 | 기여 1위 YoY · 급등·급감 수(전 품목) · 기여도 순 |
| explore.credit | 신용 긴장 Top | `/credit` | 4×3 | 시세 기준일 · 원천 미설정·4일 넘게 묵음 | 1개월 확대 1위 Δbp · 기업 수 · Δ 순 |
| explore.people | 팔로우 인물 이번 주 | `/person/followed` | 4×3 | 최근 언급 게시 시각(KST) · 36시간 | 7일 언급 1위 · 최신 문서 · 7일·Δ·함께 뜬 종목 |
| explore.actions | 오늘 기업활동 | `/actions?days=7&kind=original` | 4×4 | 마지막 DART 스캔 성공(KST) · 3시간 | 오늘 건수 · 7일·내 종목 수 · 내 종목 먼저 |
| explore.rights | 유무증 D-day | `/actions/rights` | 4×3 | 〃 | 가장 가까운 D-day · 7일 안 일정 수 · 날짜 순 |

- 프리셋: 수출 사이클에 Trade Pulse·신용 긴장 Top을, 이벤트 장세에 기업활동·유무증·팔로우 인물을 더한다.
- `GET /api/spine/person/followed` → `{items: PersonRow[], as_of}`. 팔로우 인물만, 7일 급상승 순이고, `top_stocks`는 최근 7일 문서에서 함께 뜬 종목이다.

## 6. 5-state

| | 수출입 | 회사채 | 인물 | 기업활동 | 위젯 |
|---|---|---|---|---|---|
| Empty | 팔로우 없음 → 기본 세트 버튼 | 어댑터 없음 안내 | 기간 내 인물 없음 | 원공시 없음(정정 N건 안내) | 정상적으로 비어 있음 문구 |
| Loading | Skeleton | Skeleton | Skeleton(이전 데이터 흐리게 유지) | Skeleton | Skeleton |
| Partial | 판정 없는 품목은 배지 없음 | 미수집 회사 '-' | 엣지·프로필 없음은 카드 생략 | 시총·요약 없음 '-' | 원천 고장 = 머리 시각 주의 색 |
| Error | 재시도 | 재시도 | 재시도 | 재시도 | 다시 시도 |

## 7. 검증

- 백엔드 테스트: `test_trade_hygiene`, `test_actions_filters`, `test_person_directory`.
- FE 테스트: `rights-calendar`.
- 실측(실제 DB 사본):
  - 인물 디렉토리 22.4s·899KB → 0.14s·262KB. 전체 기간 출력은 옛 구현과 3,408명 모두 같다.
  - 수출 합계 $125.7B → $84.1B. 하위 세목 40행, 라벨 22건을 정리했다.
