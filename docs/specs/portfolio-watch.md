# 종목 묶음과 기술적 감시 (Portfolio Watch)

작성일: 2026-09-19 · 상태: **P0 구현 완료(2026-09-19, D-185)** — §8 질문은 추천안대로 확정 · 담당 화면: `/follow/stocks`

## 1. 문제

관심 종목이 세 곳에 흩어져 있고, 어디에도 "매일 조건을 돌려 신호를 본다"는 기능이 없다.

| 현재 저장소 | 내용 | 상태 |
|---|---|---|
| `follows` (entity 팔로우) | 인물 12건, 기업 0건 | 관심목록 화면의 실체이지만 종목이 없다 |
| `watchlist` (레거시) | 종목 15건 · 확신도·목표가·논지 | `/follow/universe`와 종목 개요의 별 버튼에서 쓰인다 |
| `industry_groups` (유니버스) | 산업별 커버리지 그룹 | 섹터 집약·수혜 스크린의 단위. 개인 보유와는 성격이 다르다 |

전략 계산기 50개(`market_analysis/strategies.py`)와 저장 전략(발견 화면)은 전 종목 1회 검색에만 쓰인다. 사용자 요구는 반대 방향이다. 고정된 종목 묶음에 종목별로 다른 조건을 걸고, 매일 평가해 켜진 신호를 화면에서 보고 싶다.

## 2. 핵심 개념: 묶음 하나로 통일

새 객체를 두 개(포트폴리오·관심 그룹) 만들지 않고 **묶음(group)** 하나에 종류만 둔다.

- **묶음** `stock_groups`: 이름 · 종류 `portfolio | watch` · 메모 · 기본 조건 세트.
- **멤버** `stock_group_members`: 묶음 × 종목. 종류가 `portfolio`면 수량·평균 매수가·매수일을 선택 입력한다. 레거시 `watchlist`의 확신도·목표가·논지는 멤버 필드로 그대로 옮긴다.
- **감시 조건** `watch_rules`: 묶음 기본 조건 또는 특정 멤버에만 붙는 조건. 조건 본문은 전략 카탈로그 형식 `{strategy_id, params, within_days}`(D-180 계약)을 그대로 쓰고, 저장 전략을 참조할 때는 버전 번호를 고정한다. 종목별 조건은 기본 조건에 **추가**되며, 같은 `strategy_id`는 종목 조건이 기본을 덮는다.
- **평가 결과** `watch_evaluations`: (멤버, 조건, 기준일) → `pass | fail | unavailable` · value · reference · reason. 날짜별 append-only. `unavailable`은 실패로 바꾸지 않는다(D-180 규약).

### 기존 저장소와의 융화

| 기존 | 처리 |
|---|---|
| `watchlist` 15건 | 기본 묶음 "관심 종목"(종류 watch)으로 1회 이관. 확신도·목표가·논지 유지. 종목 개요의 별 버튼은 "묶음에 추가"로 바뀌고 기본 묶음에 넣는다. 레거시 API는 이관 후 읽기 호환만 남기고 제거 시점을 SYSTEM에 기록 |
| `follows` | 그대로 둔다(인물·테마 팔로우). 종목은 묶음이 담당한다고 관심목록 화면에서 분리해 보여준다 |
| `industry_groups` | 그대로 둔다. 유니버스 그룹 상세에 "이 그룹으로 묶음 만들기" 액션만 추가(복사, 연결 아님) |
| 발견 후보 목록 | 후보 행에 "묶음에 추가" 액션. 저장 전략 카드에 "이 조건으로 감시" 액션(조건 세트를 묶음 기본 조건으로 복사) |

## 3. 일일 평가

- 실행: launchd 체인(D-106, cron 금지)에 `evaluate_watch_rules`를 장 마감 시세 적재 뒤 하루 1회 추가한다. 시세가 아직 없으면 그 날은 건너뛰고 다음 회차에 소급한다(멱등: 같은 기준일 재실행은 덮어쓰지 않고 없을 때만 삽입).
- 계산: 멤버 × (기본 조건 ∪ 종목 조건)마다 `evaluate_strategy(rows, condition)`. 모델 호출 없음, 비용 0. 종목 30개 × 조건 5개 수준이면 초 단위다.
- 필요 이력: `history_requirement`로 조건별 필요 봉 수를 계산해 `stock_prices`에서 읽는다. 부족하면 `unavailable`로 남기고 사유를 기록한다.
- 발행: `pass`가 새로 켜진 날(전일 fail/없음 → 당일 pass)만 **신호**로 취급한다. 기존 `signals` 테이블에 `strategy_hit` 타입으로 발행해 홈·브리핑에 흐르게 하는 것은 P1.
- 수동 실행: 묶음 화면의 "지금 평가" 버튼(POST). 진행 상태는 `job_runs`에 남긴다(조용한 실패 금지 원칙).

## 4. 화면 `/follow/stocks`

관심목록(`/follow`) 하위 탭 "종목"으로 등록한다(`navConfig.FOLLOW_TABS`). 최상위는 `shared/PageContainer`.

1. **묶음 목록**: 카드 또는 표. 이름 · 종류 · 종목 수 · 오늘 켜진 신호 수 · 마지막 평가 시각. 새 묶음 만들기.
2. **묶음 상세**: TanStack Table(`@tanstack/react-table` v8 + shadcn Table). 열: 종목 · 현재가 · 전일 대비 · (포트폴리오) 평가손익 · 오늘 신호 · 조건 수 · 마지막 평가. 시총·등락·손익 정렬. 행 확장 또는 Sheet로 종목 조건 편집.
3. **조건 편집(Sheet)**: 카탈로그에서 전략 선택 → 매개변수 폼(카탈로그 정의의 범위 검증 재사용) → 기본/종목 조건 구분. 저장 전략 불러오기.
4. **신호 히스토리**: 묶음 또는 종목 단위 날짜별 목록. 켜진 날짜 클릭 → 기업 개요(`/analyze/:code/summary`)로 이동. 후보 차트와 같은 `CandlestickChart` 마커 재사용은 P1.

### 5-state

| 화면 | Empty | Loading | Partial | Error | Ideal |
|---|---|---|---|---|---|
| 묶음 목록 | 묶음 없음 안내 + 만들기 + 레거시 이관 제안 | Skeleton 카드 | 일부 묶음 평가 미실행 표시 | ErrorState + 재시도 | 묶음별 신호 수 |
| 묶음 상세 | 종목 없음 → 발견/검색에서 추가 안내 | Skeleton 표 | `unavailable` 종목에 사유 배지, 시세 미적재일 표시 | ErrorState, 편집 내용 보존 | 표 + 오늘 신호 |
| 조건 편집 | 조건 없음 → 카탈로그 추천 3개 | 카탈로그 로딩 | 저장 전략 버전이 바뀐 경우 알림 | 검증 오류를 필드 옆에 표시 | 기본/종목 조건 구분 표시 |
| 히스토리 | 평가 이력 없음 + 지금 평가 | Skeleton | 일부 날짜 미평가 | ErrorState | 날짜별 켜진 신호 |

## 5. API 초안

```
GET    /api/spine/groups                       묶음 목록(+오늘 신호 수)
POST   /api/spine/groups                       {name, kind, note}
PATCH  /api/spine/groups/:id
DELETE /api/spine/groups/:id
POST   /api/spine/groups/:id/members           {stock_code, quantity?, avg_price?, bought_at?}
PATCH  /api/spine/groups/:id/members/:code     수량·메모·확신도
DELETE /api/spine/groups/:id/members/:code
GET    /api/spine/groups/:id/rules             기본 + 종목별 조건
PUT    /api/spine/groups/:id/rules             전체 교체(멱등) — {default:[...], members:{code:[...]}}
POST   /api/spine/groups/:id/evaluate          수동 평가 → job_runs id
GET    /api/spine/groups/:id/signals?days=30   날짜별 pass 전이
GET    /api/spine/groups/:id/evaluations?date= 특정 날 전체 판정(unavailable 포함)
POST   /api/spine/groups/migrate-watchlist     레거시 15건 이관(1회, 멱등)
```

라우터 `routers/spine_groups.py`, 스키마 `models/groups.py`, 평가 `pipeline/watch_rules.py`(순수 계산 모듈 `strategies.py`만 호출, DB 읽기는 `stock_prices` 읽기 전용).

## 6. 범위

- **P0**: 묶음·멤버 CRUD, 기본/종목 조건, 일일 평가(launchd) + 수동 평가, 묶음 상세 표, 신호 히스토리, 레거시 `watchlist` 이관, 발견 후보 "묶음에 추가".
- **P1**: 포트폴리오 수량·매수가·평가손익, 매수가 기준 조건(손절선·목표가 도달), `signals` 발행 → 홈·텔레그램 브리핑 한 줄, 유니버스 그룹에서 묶음 복사.
- **P2**: 신호 시점 차트 마커, 조건 세트 백테스트 연결(D-180 백테스트 재사용), 즉시 알림.
- **Out of scope**: 실시간 시세, 매매 실행, 추천 종목 자동 편입.

## 7. 기각한 대안

- **`follows`(entity) 재사용**: 엔티티 단위라 수량·조건을 붙이기 어색하고 인물과 섞인다. 기업 팔로우가 0건이어서 이관 부담도 없다.
- **포트폴리오와 관심 그룹을 별도 객체로**: 사용자가 우려한 파편화 그대로. 종류 필드 하나로 충분하다.
- **묶음 공통 조건만**: 사용자 요구(종목별 조건)와 반대. 기본 + 종목 오버라이드가 편집 부담과 표현력을 절충한다.
- **LLM으로 매일 해설 생성**: 비용 의식 원칙(D-072). 판정은 결정적 계산으로 끝내고 해설은 사용자가 발견/조사 화면에서 요청할 때만.

## 8. 확인이 필요한 질문

1. 레거시 `watchlist`의 확신도(1~5)·목표가·논지를 멤버 필드로 유지할지, 버릴지.
2. 포트폴리오 수량·매수가 입력을 P0에 넣을지 P1로 미룰지(위 초안은 P1).
3. 조건 편집 UI를 카탈로그 폼으로 할지, 발견 화면의 자연어 → 조건 변환을 재사용할지(후자는 모델 비용 발생).
