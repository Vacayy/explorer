# 홈 고정 탭 · 섹션 본문

- 상태: **구현 계약(2026-11-05 화면 구조 개편 3a~3d, 7단계 정리).** 홈은 시스템 고정 탭 다섯 개다(§0). 옛 위젯 홈(격자·배치 편집·위젯 추가 창·사용자 메뉴·`/api/dashboard`)은 3a에서 화면, 7단계에서 코드·API까지 지웠다 — 옛 기록은 git 이력과 CHANGELOG에 있다.
- 이전: P4 위젯 대시보드(2026-10-16). [home-feed](home-feed.md)의 Home 시장 탭 구성을 대체했다. 피드 리더는 피드 › 피드로 남는다.
- 셸: [app-shell](app-shell.md).

## 0. 홈 고정 탭 (2026-11-05, 개편 3a)

홈 L2 = **대시보드 `/home` · 한국 시장 `/home/kr` · 미국 시장 `/home/us` · 매크로 `/home/macro` · 내 종목 `/home/stocks`**. 탭은 `navConfig`의 홈 섹션이 정한다(사용자가 만들거나 지우지 않는다). 옛 피드 주소 `/home?home_view=feed`는 `/feed`(피드 › 피드)로 리다이렉트한다(4a).

- **섹션 = 위젯 본문 재사용.** `home/HomeSection`이 레지스트리 id로 위젯의 `Body`·`useMeta`(기준 시각·주의 색)·전체 보기 경로를 빌려 쓴다. 위젯 틀(손잡이·빼기 메뉴·크기 조절)은 없다. 머리 = 제목 · ⓘ 툴팁(위젯 한 줄 설명) · 기준 시각 · 링크(지금 화면으로 가는 링크는 숨김). 본문만 오류 경계로 감싸 한 블록이 깨져도 머리와 다른 블록은 남는다.
- **대시보드**(`home/HomeDashboard`, 순서 고정): 날짜 머리 → 지수 띠 · 시장 요약 띠 → Market Overnight | Market Today(같은 높이 560/640px, 넘치면 칸 안 스크롤. 머리 링크 '미국 시장 ›'·'한국 시장 ›') → 이번 주 바뀐 서사 → 국면·리스크(상태 줄 + VIX·공포탐욕·HY·금리차 타일, 3개월 추이·20일 변화. 모바일은 VIX·공포탐욕만, 머리 링크 '매크로 ›').
- **직접 만든 블록**: 위젯이 없거나 시안과 모양이 다른 블록은 `HomeBlock`(머리 `BlockHead` + 본문 오류 경계)으로 같은 틀을 쓴다. 블록 상태는 `home/blockState`(`BlockError` 다시 시도·자세히, `RowsSkeleton` 표 모양)와 마지막 값 유지(데이터가 있으면 갱신 오류로 지우지 않음)를 따른다.
- **한국 시장**(3b, 시안 Home-KR, ia-redesign §4.2·§4.17):
  1. 국장 거래대금 상위(`home/KrTurnoverBlock`, `/api/spine/kr/movers`) | 가파른 추세(`explore.trend` 본문, 거래대금 칸 높이에 맞추고 표는 칸 안 스크롤. 모바일은 좁은 열). 거래대금 = 한 줄 요약 → 섹터 쏠림 상위 5 → 상위 10 표(신규 진입·급등락 배지, '상위 20 전체' 펼침) → '상위 5종목 관련 자료' 접기. 갱신 버튼은 머리. 가파른 추세 조건은 '어떻게 산정되나요?' 툴팁, 표 머리 '꾸준함'(R²)·'ADX' 용어 툴팁. 0종목이면 '오늘은 조건 다섯 개를 모두 통과한 종목이 없습니다'.
  2. 개인 투자 열기(`home/RetailHeatCard`, `#retail`, `/api/spine/retail`): 국면 배지 · 신용융자·예탁금·코스피 · 판정 근거 · 지표 11개 표(값·5년 백분위 막대·20일 변화) · '추이 보기 ›'(/retail). 오류는 이 블록만.
  3. 수출입(`home/TradeBlock`, `/api/spine/trade/highlights?limit=8`): 수출 총액 · 기여 1위(전년 대비·증가분 몫) · 산업별 수출 규모 상위 8(급등 수) | 평소보다 크게 늘어난 품목 8(수출액·전년 대비·전월 대비·증가분 기여). 통계월이 지난달보다 오래되면(관세청 매월 중순 발표) 'n월 기준' 칩.
  4. 기업활동(`#actions`, 시장 전체 목록 — D-300). 대만 월매출·대만 → 한국 연결은 산업 › 대만 공급망(`/follow/taiwan`)으로 옮겼다(4b).
- **미국 시장**(3b, 시안 Home-US, ia-redesign §4.3·§4.28):
  1. 실적 시즌 블록(`home/UsSeasonBlock`, `/api/spine/transcript/season`). 시즌 판정은 `lib/seasonPhase` — 오늘이 어느 시즌의 `windows[].first~last`(팔로우 기업 첫~마지막 발표일, 미확정 포함) 안이면 시즌 중, 아니면 시즌 사이. '막바지' 변형 없음.
     - 시즌 중: 시즌 이름 · '반응 집계 중 n'(첫 거래일이 아직 안 지난 발표) · 판정 줄(발표 n/팔로우 · 첫 거래일 업종보다 강함 · 하회에도 강세 · 상회에도 약세 · 첫 반응 뒤집힘) · 이번 시즌 시장이 따진 것(요약 있는 섹터 4줄, 줄 전체가 섹터 상세 링크) · '섹터 n개 모두 보기 ›' · 곧 발표 칩(D-n) · '실적 시즌 전체 ›'.
     - 시즌 사이: 머리 '다음 실적 시즌까지 D-n' + 다음 시즌 · 첫 발표일, 세 칸 = 지난 시즌 정리(마감 값 넷 + '시장이 따진 것 n개 섹터 다시 보기 ›') · 곧 발표 · 팔로우 기업(날짜별, 미확정은 '예상일') · 그 사이 볼 것(아래 브리핑 · 홈 › 매크로 · 지난 시즌 콜). 지난·다음 시즌이 서버의 '이번 시즌'과 다르면 그 시즌을 따로 부른다.
     - 팔로우 0이면 '기본 세트 팔로우'(컨콜 화면으로). 오류는 이 블록만.
     - 개발 서버에서만 `?today=YYYY-MM-DD`로 오늘을 바꿔 시즌 사이 화면을 확인한다.
  2. 어젯밤 미국장 브리핑 전문 | 거래대금 쏠림 · 개별 움직임(`UsBriefingSection columns` — 날짜 선택을 두 칸이 같이 쓴다, `#us-briefing`).
  3. 최근 받은 컨콜(곧 발표는 1의 실적 시즌 블록 하나로 — D-303) | 이번 시즌 실적 모멘텀 — 시안에는 없지만 이행 화면에 있던 것이라 남긴다(새 모멘텀 후보는 시즌 개요 개편 §4.6a로 옮겨 갈 때 정리).
- **이행 화면에서 시안으로 바꾼 탭**(기존 위젯·카드를 섹션으로 모아 둔 이행 화면 — 아무 기능도 잃지 않게 옮겼다):
  - 매크로(3c, 2026-11-05 완료): `home/HomeMacroPage` — 시안 Home-Macro·ia-redesign §4.16. 지금 시장은 5칸·AI 해설·1~5 → 매크로·유동성 신호등 → 리스크 지표 묶음(`home/RiskTiles`) → 국면 이력. 계약은 market-regimes.md §6·§8.
  - 내 종목(3d, 2026-11-05 완료): `home/HomeStocksPage` — 시안 Home-Stocks·Mobile-Stocks, ia-redesign §4.4·§4.20. 머리 줄(보기 전환·종목 추가) → 특징주 → 조건 충족 알림 줄 → 목록(추적 행 먼저, 펼치면 조건·신호·수급, 비추적 6 + 더 보기, 행마다 추적 스위치·빼기, 미국 행 실적 배지). 이행 화면의 추적 카드는 '조건 편집' 시트로, 묶음 오늘 신호는 특징주로, 관심 종목 오늘 요약은 전체 보기 아래, 포트폴리오 오늘·다가오는 일정·보유 종목 자료 흐름은 보유 보기로 옮겼다. 계약은 [stock-tracker '화면'](stock-tracker.md).
- **리다이렉트**(쿼리 유지, `KeepQueryRedirect`): `/home/b/:boardId` → `/home`, `/home/briefing` → `/home/us`, `/home/risk` → `/home/macro`, `/regimes` → `/home/macro#history`(해시는 쿼리 뒤). `/retail`은 화면을 그대로 두고 한국 시장 탭으로 판정한다.
- **5-state**(ia-redesign §4.28): 블록 단위 로딩(위젯 본문의 스켈레톤, Overnight·Today는 같은 높이 칸 안)·오류(그 블록만 '다시 시도')·빈 상태(위젯 본문 문구). Market Today는 첫 회차 전에는 직전 회차를 날짜와 함께 보인다(서버가 최신 거래일을 읽음). 리스크 타일은 갱신이 늦거나 실패하면 마지막 값을 흐리게 두고 'n일 지연 · MM/DD 값' / '갱신 실패 · MM/DD 값'을 붙인다.
- **7단계에서 걷은 것(2026-11-05)**: 섹션 목록(`widgets/registry.tsx`)에서 화면이 쓰지 않는 위젯 정의와 본문(캔버스·프록시·버크셔·신호·섹터 이동·수출입/회사채/인물/기업활동/유무증·공통 변수 노출·묶음 오늘 신호·큰 그림·내 종목 서사·흔들리는 전제·국장 거래대금·개인 투자 열기 Δ·종목 추적 위젯 정의), `WidgetDef`의 크기·분류·`Detail`·`multi`·`pick`·`titleOf`·`detailPathOf`, `react-grid-layout` 의존성, 백엔드 `/api/dashboard`(layouts·boards)와 프론트 보드 응답 계약. `home_boards`·`dashboard_layouts` 표는 데이터 보존을 위해 남긴다(읽는 곳: 일회 이관 스크립트 `scripts/migrate_tracking_to_groups.py`뿐, 백업 후 삭제 대상). 추적은 관심 종목의 추적 표시만 읽는다([stock-tracker](stock-tracker.md)).
- 3a에서 걷은 것: `home/Dashboard`(격자·편집), `home/NewBoardDialog`, `widgets/WidgetGallery`(위젯 추가 창), `widgets/rows`(줄 배치), `WidgetFrame` 틀, `SYSTEM_PRESETS`·`GALLERY_SECTIONS`, `useHomeBoards`, 홈 L2의 '+ 새 메뉴', 위젯 상세 창(`?widget=`).

## 1. 섹션 계약

```ts
interface WidgetDef {
  id: string                         // 'market.us'
  title: string                      // 머리 제목
  description: string                // 머리 ⓘ 툴팁
  detailPath?: string                // 머리 링크 '전체 보기'
  useMeta: () => { asOf: string | null; stale?: boolean }   // 기준 시각·주의 색
  Body: React.FC<{ w: number; h: number; params?: Record<string, unknown> }>   // 밀도(w·h)에 반응
}
```

1. **캐시된 GET만**: 섹션 본문은 기존 GET 훅만 쓴다. 갱신 버튼(POST)은 전체 보기 화면에만 둔다.
2. **기준 시각 = 원천 시각**: 머리 오른쪽에 응답의 `as_of`·`trade_date`·`fetched_at`. 서버 현재 시각을 쓰지 않는다.
3. **5-state + 원천 고장**: Loading=Skeleton, Error=다시 시도, Empty=정상적으로 비어 있음 문구, 원천 고장(`degraded`·`status!=ok`·`stale_days>1`)은 머리 시각을 주의 색으로 + 본문 첫 줄에 이유.
4. **요약층**: 큰 숫자 1개 + 한 줄 해석 + 목록·스파크라인. 밀도가 작으면(h≤2) 큰 숫자와 한 줄만.
5. **원천 하나**: 금리·VIX·공포탐욕은 정본(`risk_*`, D-236)만 읽는다.

## 2. 섹션 목록 (화면이 쓰는 id만)

| id | 이름 | 원천 | 쓰는 곳 | 내용 |
|---|---|---|---|---|
| market.indices | 지수 띠 | `/indices` | 대시보드 | 지수별 값·등락 · 1Y 스파크 가로 띠 |
| market.context | 시장 요약 | `/macro` | 대시보드 | 환율·금리·유가·금·BTC 가로 띠 · 올리면 추이 차트(`MetricTrend`) |
| market.us | Market Overnight | `/us/briefing` | 대시보드 | `UsBriefingSection embedded` 전체(핵심 요약 bullet 먼저)를 칸 안에서 스크롤 |
| market.today | Market Today | `/spine/market-today` | 대시보드 | 회차 칩·텔레그램/뉴스 건수·다음 정리 시각 · 화두 — docs/specs/market-today.md |
| risk.regime | 시장 국면 | `/market-regime` | 대시보드 | 국장·미장 포스처 · 근거 한 줄 |
| risk.curve · risk.vix · risk.fear · risk.hy | 금리차 · VIX · 공포·탐욕 · HY | `/risk?range=3m&keys=curve,vix,fear_greed,hy` | 대시보드 | 값 · 20일 변화 · 3개월 스파크, 늦거나 실패하면 마지막 값 흐리게 + 기준 날짜 |
| explore.trend | 가파른 추세 | `/spine/trend-leaders` | 한국 시장 | 아래 조건 |
| explore.calls · explore.momentum | 최근 받은 컨콜 · 새 모멘텀 후보 | `/spine/transcript/recent` · `/spine/transcript/momentum` | 미국 시장 | 발표일 순 10 · 점수 상위 3(→ `?view=season&pick=`) |
| explore.twRevenue · explore.twLinks | 대만 월매출 · 대만 → 한국 연결 | `/spine/tw/revenue` · `/spine/tw/links` | 산업 › 대만 공급망 | docs/specs/tw-revenue.md |
| world.changes | 이번 주 바뀐 서사 | `/spine/world/changes?days=7` | 대시보드 | 최근 7일 새 버전 · 옮겨 간 내용 1~2문장 |
| portfolio.today · portfolio.events · portfolio.flow | 포트폴리오 오늘 · 다가오는 일정 · 보유 종목 자료 흐름 | `/portfolio`·`/portfolio/history` · `/portfolio/events` · `/portfolio/flow` | 내 종목(보유 보기) | 비율·날짜만(D-212) |
| watch.digests | 관심 종목 오늘 요약 | `/spine/groups/{id}/digests` | 내 종목(전체 보기) | 최신 요약일 · 종목별 '새로운 점' 또는 첫 줄 |

종목 추적 카드 본문(`widgets/tracker`의 `TrackerBody`)은 섹션 목록에 없고 내 종목 화면의 '조건 편집' 시트가 직접 쓴다.

**가파른 추세 조건**(`pipeline/trend_leaders.py`, 모두 AND): 시총 3,000억+ · 60거래일 +30%+ · 60거래일 log(종가) 회귀 R² 0.75+ · 종가>MA20>MA60, MA60이 20거래일 전보다 높음 · ADX(14) 25+ & +DI>−DI. 순위 = 연율 로그 기울기 × R². LLM 0·네트워크 0.

**52주 신고가 단계**(추세 통과 종목만, `high52_stage`, 2026-10-22): 전고점 = 그날의 직전 250거래일 최고가.
- 신고가 돌파: 최근 5거래일 안에 종가가 전고점을 넘었다.
- 돌파 후 지지·재반등: 60거래일 안에 전고점을 돌파(20거래일 넘게 신고가가 없던 뒤 첫 돌파 — 오르는 동안 매일 생기는 신고가가 아니라 깨진 전고점) → 돌파 뒤 저점이 돌파선 −5%~+3% 안, 종가는 −3% 아래로 안 빠짐 → 그 저점 뒤 다시 올라 오늘 종가가 돌파선과 저점 날 종가 위.
- 목록은 상위 20 + 단계가 붙은 종목(순위 밖 포함).

**이벤트**(같은 모집단, 추세 조건과 별개): 52주 신고가 돌파 = 최근 5거래일 안에 종가가 직전 250거래일 고가 최고치를 처음 넘음(지금 그 선 아래면 표시). 매물대 돌파 후 지지 = 20거래일 전까지 250거래일의 최대 매물대(종가·거래량 20구간 POC) 윗선을 최근 20거래일 안에 종가로 돌파하고 2거래일 이상 지나, 되돌림 저가가 그 선 −2%~+3%에서 멈추고(종가 이탈 없음) 오늘 종가가 선 위.

**갱신 주기**: 따로 도는 잡이 없다. GET 때 stock_prices로 계산하고 (최신 거래일, 그날 행의 최신 fetched_at)이 같으면 메모리 캐시를 쓴다. 시세 수집(평일 16:35, 20:20 재수집)이 끝나면 다음 조회에서 다시 계산된다.

## 3. 검증

- 3b(2026-11-05): `tests/home-us-season.test.tsx`(시즌 중·사이 판정 경계, D-n 날짜 계산, 곧 발표 날짜 묶음·예상일, 수출입 통계월 지연 판정, 시즌 블록 시즌 중·시즌 사이 렌더), 1440·390 화면 확인(`/home/kr`·`/home/us`·`/home/us?today=2026-12-24`·`?today=2027-01-03`·`/follow/transcripts?view=season`·`/retail`·`/home`, 콘솔 오류 0).
- 3a(2026-11-05): `tests/app-shell-nav.test.mjs`(홈 탭 다섯·옛 주소 판정·리다이렉트·메뉴 UI 없음), `tests/home-section.test.tsx`(블록 단위 오류·링크 숨김), 1440·390 화면 확인(`/home`·`/home/kr`·`/home/us`·`/home/macro`·`/home/stocks`·리다이렉트 3개, 콘솔 오류 0), 추적 대상 6종목 그대로.
- 7단계(2026-11-05): 쓰지 않는 위젯·API 제거 뒤 `tsc`·eslint·build·vitest·node 테스트·`contracts:live`, 1440·390 전 경로 화면 확인.
