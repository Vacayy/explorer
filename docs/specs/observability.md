# 관측 — 잘 도는가 · 얼마나 드는가 · 무엇을 쓰는가 · 도움이 되는가

상태: **P0 구현(2026-10-31)** · **개편 IA 대응(2026-11-06)**: 이름 정규화·핵심 동작·IA 집계·옛 주소 분리·무입력 상한·자동화 브라우저 제외·생성 대비 열람. 보관 정리는 P2로 미룸.
관련: [데이터 신선도 점검](ops-health.md) · [프론트 API 안정성](frontend-api-reliability.md)

## 목표

이 시스템은 사용자 1명·로컬 노트북·SQLite·launchd 정기 작업·LLM 생성 위주다. 외부 관측 도구(Datadog·Sentry·PostHog·Grafana)는 운영 부담이 가치보다 커서 쓰지 않는다. **기록은 지금처럼 SQLite에 쌓고, 보는 곳 하나(관리자 '관측' 탭)와 알림 하나(주간 텔레그램 + 상태가 바뀔 때만 경고)를 만든다.**

지표는 네 질문으로 나누고, 각 지표는 그것으로 내릴 결정에 묶는다. 결정으로 이어지지 않는 지표는 만들지 않는다.

| 질문 | 결정 |
|---|---|
| 잘 도는가(안정성) | 무엇을 먼저 고칠지 |
| 얼마나 드는가(효율) | 무엇을 줄일지 |
| 무엇을 쓰는가(사용) | 무엇을 키우고 무엇을 접을지 |
| 도움이 되는가(효용) | 만들고 안 보는 생성을 멈출지 |

## 이미 있는 것과 빈 곳 (2026-10-31 실측)

| 원천 | 내용 | 규모 |
|---|---|---|
| `job_runs` | 정기 작업 상태·요약·소요시간 | 11,670건 |
| `llm_calls` | LLM 호출마다 job·모델·토큰·캐시·비용·소요·성공 | 33,401건(9/8~) |
| 운영 점검 `/api/spine/admin/health` | 데이터 신선도·launchd·화면 API 오류·백엔드 코드 반영 | — |
| `client_errors` | 화면 API 계약 위반·5xx·timeout | 오늘부터 |

보는 곳이 없어 놓친 것(지난 7일): LLM 비용 $76.7 중 **이미지 백필 $38.7(51%)**, 20,887회 · 장중 포트폴리오 알림 **12회 실패**(DB 잠김·연결 오류) · 외부 시계열 수집 **7회 모두 부분 성공**(매번 일부 실패, 실패로 집계되지 않음).

빈 곳: 서버 API 요청 단위 기록(응답시간·5xx), **사용 기록 전무**, 효용 신호 전무.

## 데이터 계약

### 1. API 요청 집계 `api_requests_hourly` (새)

FastAPI 미들웨어가 요청마다 **경로 패턴**(`/api/spine/us/{ticker}`, 실제 값 아님)·메서드·상태 계층으로 메모리에 모았다가 1분마다 시간 단위 행에 더한다(요청마다 행을 쌓지 않는다).

- 키: (hour UTC, method, route, status_class 2xx|4xx|5xx)
- 값: count, total_ms, max_ms, 응답시간 구간별 건수(≤100·≤300·≤1000·≤3000·>3000ms) — p95는 구간으로 근사
- 제외: `/api/spine/client-errors`, `/api/spine/usage`, 정적 파일, `x-observe-skip: 1` 요청(정기 실제 응답 검사)

### 2. 사용 이벤트 `usage_events` (새)

프론트가 보낸다(`lib/usage.ts`, `shared/UsageTracker`). 이벤트 종류는 아래로 고정한다(새 종류·이름은 스펙에 먼저 추가).

| type | 언제 | name | 추가 |
|---|---|---|---|
| `view` | 화면 진입(라우트 변경) | 화면 이름(아래 규칙) | ref(직전 화면), entity(티커·종목코드·id) |
| `leave` | 화면 이탈·탭 숨김 | 같은 이름 | dwell_ms(보이고 입력이 있는 동안만 셈) |
| `action` | 상태를 바꾸는 핵심 동작 | 아래 동작 표 | entity |
| `open` | 무언가를 열어 읽음(팝오버·대화상자·물방울·전문·원문) | 아래 동작 표 | entity, ref(부모 대상 id가 따로 있을 때) |

모든 이벤트에 **section·tab**(IA 위치)을 붙인다 — `navConfig.locate(pathname, search)`의 대메뉴·탭, L1 밖은 `dossier`(탭 = 도시에 탭·`us`) · `chat` · `admin`(탭 = `?view`). view·leave는 그 화면의 위치, action·open은 일어난 순간의 주소. 개편 전 행은 NULL(관측 탭 '이전 기록').

**화면 이름 규칙**(`screenOf`)
- 경로 값은 패턴으로: `/analyze/:stockCode/:tab`(탭 값은 이름에) · `/us/:ticker` · `/doc/:docId` · `/question/:id` · `/study/projects/:id` · `/study/:id` · `/industry/:sector` · `/follow/trade/:hs` · `/follow/taiwan/:code` · `/person/:id` · 옛 `/home/b/:boardId` · `/company/:stockCode/:tab` · `/synthesis/:synthesisId`. 값은 entity로.
- 화면을 가르는 쿼리는 값까지 이름에: `view` · `tab` · `home_view`(옛 피드 주소 `/home?home_view=feed`를 가른다).
- 상세를 여는 쿼리는 있는지만 이름에(`/follow/transcripts?t`), 값은 entity: `t` · `topic`.
- 화면 안 상태 쿼리는 이름에 넣지 않고 entity로: `group` · `stock` · `sector` · `hs`·`tw`(수출입·대만 대화상자).
- **같은 화면 안 변화는 방문이 아니다**: 이름과 경로 값이 같고 상세·상태 쿼리 값만 바뀌면 view·leave 대신 아래 이벤트 하나(ref = 화면 이름). 값이 사라지는 것(닫기)은 남기지 않는다. 그 밖의 쿼리(정렬·쪽 등)는 남기지 않는다.

| 쿼리 | 이벤트 |
|---|---|
| `group` | action `peer.group` |
| `stock` | action `peer.stock` |
| `sector` | action `season.sector` |
| `t` | open `transcript.open` |
| `topic` | open `narrative.open` |
| `hs` · `tw` | open `monitor.open`(entity = HS 코드·대만 종목 코드) |

**핵심 동작**(코드에서 직접 `track`) — 이름표는 `admin/ObservePanel`의 `ACTION_KO`

| type | name | 어디 | entity |
|---|---|---|---|
| action | `reaction.make`·`expectation.make`·`digest.make`·`prices.collect`·`transcript.collect`·`transcript.check`·`chat.ask`·`chat.attach`·`study.add`·`save`·`watch.add`·`watch.remove`·`core.pin`·`core.unpin`·`overview.make` | 개편 전부터 | 티커·종목코드·id |
| open | `ai_outputs.open` | 상단 바 'AI가 최근 만든 것' 팝오버·폰 메뉴 줄 | — |
| open | `ai_outputs.click` | 그 목록의 산출물 줄 | 타임라인 id(`narrative:12`) 또는 `종류:생성시각` |
| action | `monitor.detail` | 모니터 대화상자 '상세 페이지 ›' | HS 코드·대만 종목 코드 |
| open | `transcript.stage` | 콜 상세 네 단계 '자세히 보기' | `before`·`call`·`reaction`·`after`, ref = 콜 id |
| open | `transcript.fold` | 콜 상세 펼치기 줄(핵심 정리·반응 전문·온톨로지·원문) | 펼치기 줄 이름(고정 라벨) |
| open | `overnight.full` | Market Overnight '브리핑 전체 보기'·'전문' | 거래일 |
| action | `feed.source` | 피드 소스 고르기 | 채널 id |
| open | `feed.original` | 피드 글 '원문 보기' | 문서 id |
| action | `feed.mark_all_read` | 피드 '모두 읽음' | 소스 종류 |
| action | `narrative.week` | Thesis 지금 '이번 주 바뀐 것' 켜기 | — |
| action | `narrative.expand` | 서사 행 고리 변화 펼치기 | 서사 topic |
| action | `ontology.expand` | 그래프 노드 늘리기(150·300) | 늘린 뒤 노드 수 |
| action | `index.switch` | 홈 시장 지수 차트 지수·기간 | `kospi:1m` 형식 |
| action | `market_today.nav` | 장중 정리 날짜 이전·다음·오늘로·회차 칩 | `prev`·`next`·`today`·`slot:<시각>` |

섹터 화면 탭(`sector.tab`)은 주소(`?tab`)라 화면 이름으로 이미 갈린다.

- **내용은 넣지 않는다**: id·키·고정 라벨만. 검색어·메모 본문·질문 글·금액·수량은 넣지 않는다.
- 세션: 탭이 열린 동안 하나(sessionStorage), 30분 무활동이면 새 세션.
- **머문 시간 무입력 상한**: 입력(pointer·키·휠·스크롤·터치·탭 다시 보임)이 5분 없으면 그 5분까지만 세고 시계를 멈춘다. 입력이 오면 다시 센다(켜 둔 채 자리를 비운 시간 제외 — 11-06 `/follow/trade` 한 번 34.8분 사례).
- 보내기: 묶어서 10초마다 또는 화면 이탈 시 `fetch(keepalive)`(sendBeacon은 교차 출처 JSON을 못 보낸다). 실패해도 화면에는 영향 없음.
- **보내지 않는 곳**: 테스트 환경(vitest), 자동화 브라우저(`navigator.webdriver` 또는 UA `HeadlessChrome`) — 점검 스크립트가 사용 기록을 부풀리지 않게. 자동화 브라우저로 기록 자체를 점검할 때만 `localStorage['explorer.usage.force']='1'`로 켠다(점검 뒤 지운다).
- 개인 투자 내용(금액·수량·메모 본문)은 넣지 않는다. 로컬에만 둔다.

### 3. 보관

원본 이벤트·요청 집계는 **90일**, 그 뒤 일별 집계(`usage_daily`, `api_requests_daily`)만 남긴다(P2 — 1인 사용 규모로는 수년 뒤에야 의미가 있어 P0에서 뺐다).

## 지표

| 질문 | 지표 | 원천 |
|---|---|---|
| 안정성 | 작업별 성공률·**연속 실패**·**만성 부분 성공**(최근 N회 모두 partial) · API 경로별 5xx 비율·p95 · 화면 API 오류 · 데이터 신선도 | job_runs · api_requests_hourly · client_errors · health |
| 효율 | 작업별 LLM 비용·호출·캐시 적중률·실패율 · 지난주 대비 · **결과물당 비용**(반응 정리 1건·핵심 정리 1건 등) | llm_calls + 결과 테이블 |
| 사용 | 메뉴(section→tab)별 방문·머문 시간·동작 · 화면별 방문·머문 시간 · 자주 가는 경로(직전→다음 화면 상위) · 핵심 동작·열람 횟수 · 지난달엔 열었는데 이번 주 안 연 화면 · 옛 주소 접근 | usage_events · api_requests_hourly |
| 효용 | **생성 대비 열람률**(자동으로 만든 것 중 열어본 비율) · 다시 열어봄 · 열람 후 행동(저장·스터디·채팅) · 시스템 판단 채점(발표 전 기대 맞힘률 등) | usage_events + 생성 테이블 + 기존 채점 |

'생성 대비 열람률'이 효용의 중심이다. 비용 대부분이 LLM이 미리 만드는 데서 나온다 — 열지 않는 생성은 줄이거나 '열 때 생성'으로 바꾼다(유튜브 정리본에서 한 판단을 기능 전체로).

## 화면 — 관리자 '관측' 탭 (`/admin?view=observe`)

시즌 화면과 같은 형식: 섹션 하나에 카드 하나, 안은 소제목과 불릿, 숫자는 문장 안에.

1. **이번 주 한눈에**: 네 질문 각각 한 줄 + 지난주 대비.
2. **잘 도는가**: 지금 문제(연속 실패·만성 부분 성공·5xx 많은 API·화면 API 오류) → 작업별 성공률 표(접힘).
3. **얼마나 드는가**: 일별 비용 막대(14일) · 작업별 비용 상위와 캐시 적중률 · 결과물당 비용.
4. **무엇을 쓰는가**: 메뉴별(대메뉴 방문·평균 머문 시간·동작, 아래 줄에 탭별) · 자주 연 화면 · 자주 가는 경로 · 핵심 동작 · 안 쓰는 화면 · 옛 주소 접근.
   - **안 연 화면 vs 옛 주소**: 리다이렉트만 남은 옛 주소(`pipeline/observe.py OLD_ROUTES` — App.tsx 리다이렉트·ia-redesign §10.6, 쿼리로 옮긴 `/home?home_view=feed`·`/follow/transcripts?view=proxies` 포함)는 '이번 주 안 연 화면'에서 빼고 '옛 주소 접근 n회'(이름·횟수·어디서 왔는지 상위 3)로 따로 보인다. 같은 칸에 `api_requests_hourly`의 `/api/dashboard/boards*` 호출 수 — 0이 이어지면 `home_boards`·`dashboard_layouts` 표를 백업 후 지운다.
   - 개편 전 행(section 없음)은 메뉴별 맨 아래 '이전 기록'으로 묶는다(경로로 거꾸로 판정하지 않는다 — 옛 주소가 섞여 판정이 틀린다).
5. **도움이 되는가**: 생성 대비 열람 · 열람 이벤트별 횟수 · 시스템 판단 채점.
   - 생성 대비 열람(`value.rates`): **AI가 최근 만든 것** = 기간 안 narratives·reports·scenarios·entity_digests·유튜브 정리(ok) 수 대비 `ai_outputs.click` 서로 다른 entity · **컨콜 핵심 정리·시장 반응** = 기간 안 정리가 붙은 콜 ∪ 반응 정리 수 대비 `transcript.stage`(entity call·reaction) 서로 다른 콜(ref) · **어젯밤 미국장 브리핑** = `us_briefings` 수 대비 `overnight.full` 서로 다른 거래일. 생성 수는 근사(같은 산출물이 다른 길로 열리면 세지 않는다).

5-state: 수집 전(사용·효용은 '수집 시작 후 N일 뒤부터')·로딩·부분(일부 원천만)·오류·정상.

## 알림

- **주간 텔레그램**(월 07:05, 기존 월요일 07:00 브리핑 뒤): 한 화면 분량. 네 질문 각 1~2줄 + 이번 주 할 일 상위 3. 사용 줄에 메뉴별 방문 상위 5 · 옛 주소 접근·옛 홈 보드 API 수, 효용 줄에 생성 대비 열람(만든 것이 있는 항목만).
- **즉시 경고**(상태가 바뀔 때만, 같은 경고는 하루 1회): 작업 연속 3회 실패 · 하루 LLM 비용이 지난 14일 중앙값의 2배 · API 5xx 비율 5% 초과(시간당 20건 이상일 때).

## 단계

- **P0(구현됨)**: API 요청 집계 미들웨어 · 사용 이벤트(view·leave·action) · 관측 탭 · 주간 리포트 · 즉시 경고(연속 실패·비용 급증·5xx) · 만성 부분 성공 감지
- 새 핵심 동작을 만들면 위 표에 먼저 넣고 `track('action'|'open', '<name>')`을 붙인 뒤 `ObservePanel`의 `ACTION_KO`에 추가한다. 상태를 바꾸면 action, 읽으려고 열면 open.
- **P1**: ~~생성물 `open` 이벤트와 생성 대비 열람률~~(11-06) · 결과물당 비용 · 생성물 👍/👎(가치가 불분명한 생성물에만)
- **P2**: 평소 대비 이상 감지 다듬기, 보관 정리 자동화
