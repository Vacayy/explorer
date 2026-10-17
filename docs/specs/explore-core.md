# 탐색 핵심 — 종목 발견 · 신호 · 컨콜 · 산업·섹터 (P6a)

- 상태: 구현 계약 (2026-10-16). 셸: [app-shell](app-shell.md) 탐색 L2. 위젯: [home-widgets](home-widgets.md) §2 계약.
- 세부 기능 계약은 각 담당 spec에 있다: 발견 워크스페이스 [technical-reading](technical-reading.md)·[market-strategies](market-strategies.md), 컨콜 [transcript-follow](transcript-follow.md)·[transcript-momentum](transcript-momentum.md), 섹터 서사 [sector-aggregation](sector-aggregation.md). 이 문서는 탐색 탭 4개의 화면 묶음과 위젯만 정한다.
- URL은 바꾸지 않았다. 옛 경로는 리다이렉트한다.

## 1. 종목 발견 `/discover`

워크스페이스는 그대로다. **추천 조건 묶음은 한 목록**이다.

| 항목 | 내용 |
|---|---|
| 정본 | `pipeline/market_analysis/discovery_service.PRESETS` (24개) |
| 필드 | `id` · `scenario`(rising 상승 후보 · recovery 반등·전환 · other 방향 미정) · `group`(라이브러리 묶음) · `name` · `tag` · `purpose` · `misses`(상황 렌즈가 못 보는 것) · `phrase`(문장으로 찾기에 덧붙일 조건 문장) · `conditions` |
| 읽는 곳 | 좌측 '빠른 시작'(scenario로 거름) · 라이브러리 '검색 제안' · 문장으로 찾기 '조건 추가' · 후보의 역방향 추천 |
| 규칙 | 방향 없는 관찰(스퀴즈·거래량 급증·52주 신저가)은 `rising`에 넣지 않는다. `?intent=<id>` 옛 링크는 그 묶음의 scenario로 범위를 복원한다(other → 모든 상황) |

예전의 FE 상수(`DISCOVERY_SCENARIOS` 12) · `LENSES` 8 · 인라인 templates 16은 삭제했다.

## 2. 신호 `/explore`

- 인덱스: 유형 8개 카드(언급 급증·주목 주제·소외·52주 신고가·거래량 급증·가격-관측 괴리·컨센서스 극단·**실적 발언 모멘텀**). 카드 = 그 유형 최신일 건수(큰 숫자) · 7일 건수 · 상위 3 칩 · 목록 링크. 유형 최신일이 전체 기준일보다 2일 넘게 뒤처지면 날짜를 주의 색으로.
- 원천: `GET /api/spine/signals/summary?days=7` — 유형별 `latest_date`·`count_latest`·`count_window`·`top[3]`(유형별 세기 순: 언급 수·점유율 변화·시총·돌파율·거래량 배수·|3개월 수익|·쏠림 비율·점수). `as_of` = 신호 최신일. 읽기 전용.
- `?list=<type>`: 기존 카드 목록. 기간 30일, 주목 주제 14일, 실적 발언 모멘텀 90일(시즌 신호).
- 칩 목적지: 국내 종목 → `/analyze/:code/summary`, 미국(`payload.ticker`) → `/us/:ticker`, 그 외 → `/feed?q=`.
- 5-state: Skeleton 8칸 · ErrorState · 신호 0건 EmptyState · 유형 하나 없음 → 카드에 '아직 신호가 없습니다' · 묵은 유형 → 주의 색 날짜.

## 3. 컨콜 `/follow/transcripts` (+ `/us`)

- 하위 탭(`TranscriptTabs`): 컨콜 · 실적 모멘텀(`?view=momentum`) · 미국 기업(`/us`) · 프록시(`?view=proxies`). `/us` 디렉토리도 같은 탭 줄을 보인다.
- 컨콜 보기 맨 위에 **모멘텀 띠**: 이번 시즌 이름 · 발표 분석 수 · 새 모멘텀 수 · 상위 3 티커(점수) · 자세히.
- **실적 캘린더 '곧 발표'**: `transcript_calendar`(yfinance). 조회 실패한 종목은 쓰지 않는다(기존 발표일·`checked_at` 유지 → 다음 실행이 다시 묻는다). 연속 5회 실패면 네트워크 장애로 보고 중단. 비었을 때 '발표일을 아는 기업 k/N · 마지막 확인 M/D'를 보인다(`/follow` 행의 `calendar_checked_at`).
- `GET /transcript/momentum` 응답에 `as_of`(마지막 판정 시각, `call_momentum.computed_at` 최대, UTC).

## 4. 산업·섹터 `/map`

| `?view=` | 화면 | 원천 |
|---|---|---|
| `map`(기본) | 산업 맵 — 18 대분류 RS 사분면·구성표·밸류체인·소속 종목 | `sector_map` · `sector_rs` |
| `universe` | 유니버스 — 커버리지 큐레이션·섹터 서사·리포트 | `industry_groups/members` |
| `chains` | 산업군 지도 — 밸류체인 표·지도 | `industry_groups/members` |

- 옛 경로: `/follow/universe` → `/map?view=universe`, `/discover/industry` → `/map?view=chains`.
- 산업 맵 선택 섹터 = `?group=<대분류>`. 선택되면 밸류체인·소속 종목을 구성표 **위**에 보이고 산점도의 다른 점을 흐린다. 소속 종목이 없으면 그 사실을 문구로.
- 교차 링크: 국장 거래대금 섹터 쏠림 라벨 → `/map?group=`. 유니버스 그룹 → '산업 맵에서 보기' 칩 = 멤버가 속한 `sector_map` 대분류 상위 3(`GET /api/industries/{id}` 응답 `map_groups: [{name, members}]`).
- 두 섹터 체계(`sector_map` 18 대분류 · `industry_groups` 11 큐레이션)는 **합치지 않는다**. 이름이 달라 멤버 분포로만 잇는다. 통합 여부는 별도 결정.

## 5. 위젯 (탐색 탭, `widgets/explore.tsx`)

| id | 이름 | 원천 | 기본 크기 | 큰 숫자 · 한 줄 · 목록 | 고장 표시 |
|---|---|---|---|---|---|
| explore.signals | 오늘의 신호 | `/signals/summary` | 4×3 | 기준일 건수 · 유형 수 · 유형별 건수+상위 칩 | 신호 최신일 1일 초과 |
| explore.momentum | 이번 시즌 실적 모멘텀 | `/transcript/momentum` | 4×4 | 새 모멘텀 수 · 시즌·발표 분석 수 · 상위 3(티커·점수·대표 동인) | 판정 2일 초과 · SEC 미설정 |
| explore.calls | 컨콜 · 실적 발표 | `/transcript/follow` + `/transcript/recent?days=7` | 4×5 | 위: 곧 발표할 팔로우 기업(D-day·발표일, 가까운 순 — 컨콜 탭 '곧 발표'와 같은 원천) · 아래: 7일 수집 수 · 발표일 순 목록(받은 순 아님) | — (머리 = 마지막 수집 KST) |
| explore.sectorShift | 섹터 사분면 이동 | `/sector-map` | 4×4 | 사분면이 바뀐 대분류 수 · 1주 전 → 지금 · 단기 RS 변화 큰 순 | 시세 기준일 3일 초과 |

사분면: 장기 RS ≥50·단기 ≥50 주도 / 장기 <50·단기 ≥50 부상 / <50·<50 소외 / ≥50·<50 과열·경계 (`hooks/useSectorMap.quadrantOf`).

## 6. 검증

`tsc -p tsconfig.app.json` · FE `node --test tests/*.test.mjs`(빠른 시작 범위 규칙) · 백엔드 `test_transcript_calendar`(실패가 기존 값을 지우지 않음·장애 중단·정상 기록) · `test_signals_summary`(유형별 최신일·상위 순·빈 상태) · `test_market_discovery`(PRESETS 한 목록·id 중복 없음·방향 미정은 상승 아님). 실제 화면: 탭 4개, `/map?group=`, 옛 경로 리다이렉트, 위젯 추가 창 탐색 탭에서 4종 추가.
