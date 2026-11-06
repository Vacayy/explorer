# 홈 고정 탭 · 섹션 본문

- 상태: **구현 계약(2026-11-05 화면 구조 개편 3a~3d, 7단계 정리 · 2026-11-06 한국·미국 시장 공통 틀, D-325).** 홈은 시스템 고정 탭 다섯 개다(§0). 옛 위젯 홈(격자·배치 편집·위젯 추가 창·사용자 메뉴·`/api/dashboard`)은 3a에서 화면, 7단계에서 코드·API까지 지웠다 — 옛 기록은 git 이력과 CHANGELOG에 있다.
- 이전: P4 위젯 대시보드(2026-10-16). [home-feed](home-feed.md)의 Home 시장 탭 구성을 대체했다. 피드 리더는 피드 › 피드로 남는다.
- 셸: [app-shell](app-shell.md).

## 0. 홈 고정 탭 (2026-11-05, 개편 3a)

홈 L2 = **대시보드 `/home` · 한국 시장 `/home/kr` · 미국 시장 `/home/us` · 매크로 `/home/macro` · 내 종목 `/home/stocks`**. 탭은 `navConfig`의 홈 섹션이 정한다(사용자가 만들거나 지우지 않는다). 옛 피드 주소 `/home?home_view=feed`는 `/feed`(피드 › 피드)로 리다이렉트한다(4a).

- **섹션 = 위젯 본문 재사용.** `home/HomeSection`이 레지스트리 id로 위젯의 `Body`·`useMeta`(기준 시각·주의 색)·전체 보기 경로를 빌려 쓴다. 위젯 틀(손잡이·빼기 메뉴·크기 조절)은 없다. 머리 = 제목 · ⓘ 툴팁(위젯 한 줄 설명) · 기준 시각 · 링크(지금 화면으로 가는 링크는 숨김). 본문만 오류 경계로 감싸 한 블록이 깨져도 머리와 다른 블록은 남는다.
- **대시보드**(`home/HomeDashboard`, 순서 고정): 날짜 머리 → 지수 띠 · 시장 요약 띠 → Market Overnight | Market Today(같은 높이 560/640px, 넘치면 칸 안 스크롤. 머리 링크 '미국 시장 ›'·'한국 시장 ›') → 이번 주 바뀐 서사 → 국면·리스크(상태 줄 + VIX·공포탐욕·HY·금리차 타일, 3개월 추이·20일 변화. 모바일은 VIX·공포탐욕만, 머리 링크 '매크로 ›').
- **직접 만든 블록**: 위젯이 없거나 시안과 모양이 다른 블록은 `HomeBlock`(머리 `BlockHead` + 본문 오류 경계)으로 같은 틀을 쓴다. 블록 상태는 `home/blockState`(`BlockError` 다시 시도·자세히, `RowsSkeleton` 표 모양)와 마지막 값 유지(데이터가 있으면 갱신 오류로 지우지 않음)를 따른다.
- **한국 시장 · 미국 시장 공통 틀**(2026-11-06, D-325, 시안 Home-KR·Home-US, ia-redesign §4.2·4.3·§4.17·§4.28). 두 탭은 같은 띠 순서·높이를 쓴다. 띠 = 12칸 격자(`home/MarketFrame` `Band`, 칸끼리 테두리 겹침, 768 미만은 한 줄), 칸 = `MarketCard`(안쪽 16/18 · 세로 12 · 높이 고정 `shared/Bounded` `BAND`).

  | 띠 | 높이(넓은 · 좁은) | 한국 | 미국 |
  |---|---|---|---|
  | ① 지수 | 380 · 내용(차트 220 + 지표 2×2) | 지수 차트 8 \| 요약 지표 2×2 4 (`home/MarketHero`) | 같음 |
  | ② 시장 정리 | 440 · 420 | 오늘 시장 이야기 7(`MarketTodayCard`) \| 거래대금 쏠림 5 | 어젯밤 미국장 7(`OvernightCard`, `#us-briefing`) \| 거래대금 쏠림 5 |
  | ③ 종목 | 500 · 420 | 거래대금 상위 7(10개씩) \| 가파른 추세 5 | 거래대금 상위 7(실적 열) \| 새 모멘텀 후보 5 |
  | ④ 실적·이벤트 | 460 · 400 | 국내 실적 시즌 7 \| 기업활동 5(`#actions`) | 실적 시즌 7(`home/UsSeasonBlock`) \| 최근 컨콜 5 |
  | ⑤ 시장 고유 | 400 · 400 | 개인 투자 열기 6(`#retail`) \| 수출입 6 | 없음 |

  - **넘침**: 칸 안 목록은 `FillArea`(공식 ScrollArea, 남은 높이를 채움)로 스크롤, 순서가 있는 긴 목록은 `shared/PagerBar`(공식 ui/pagination — 'n–m / 전체' · ‹ 번호 ›) — 거래대금 표 10개, 기업활동·최근 컨콜 6개. 보기 전환·페이지·근거 창을 눌러도 칸과 아래 띠는 움직이지 않는다(4px 이하, 클릭 점검 스크립트로 확인).
  - **URL 상태**: `idx`(지수 키)·`range`(1d·1m·3m·1y), `mtslot`(Market Today 회차), `trend_tab`·`trend`(가파른 추세 보기·근거 창), `acts`(기업활동 all·mine·pro), `brief`(key·full), `mom`(new·cont). 기본값이면 쿼리에서 지운다(`hooks/useUrlParam`).
  - **① 지수 차트**: 원천 `GET /api/spine/market/{kr|us}/overview`(저장분만, 아래 계약). 큰 값 · 기준 대비(1일 = 전일 종가, 기간 = 기간 시작 전 값) · 기준 이름 · 상태 줄('11/5(목) 15:30 마감', 장중 'HH:MM 기준', 미국은 '현지 16:00 마감 · 한국 11/6 06:00', 개장 전은 '개장 전 · '). 차트 `charts/IndexLineChart`(SVG 1000×200, 점선 기준선 + '기준 값' 표, 선·면 색 = 등락 방향, 1일 x = 개장~마감 시각 비율 → 장중엔 지금 시각에서 멈춘다, 개장 전 1일은 직전 거래일 경로를 흐리게). 요약 지표 칸 = 이름(ⓘ) · 값(Geist 24) · 보조 줄(칸마다 기준일) · 20일 추이(시장 폭은 상승·보합·하락 막대, 개인 순매수는 0선 위아래 막대, 공포·탐욕은 0~100 막대 + 추이).
  - **② 한국**: 회차 칩(09:30 · 11:30 · 15:00 · 16:00 마감, 아직 안 나온 회차는 비활성) → AI 줄 → 화두(본문 전부 · 출처 · 내러티브 칩). 첫 회차 전에는 머리·칩을 그대로 두고 목록 자리에 '오늘 첫 정리는 HH:MM에 나와요.' 한 줄. **미국**: 요약 한 줄(15/600) → 핵심 다섯 줄 | 전문(`BriefingProse`, 같은 높이 안 전환). 어젯밤 장이 아니거나 정기 생성 실패·stale이면 회색 줄을 주의 색으로, 이유·빠진 재료는 ⓘ. 날짜 고르기는 두지 않는다(대시보드 물방울 전문·`/feed`의 Explorer 산출물로).
  - **② 거래대금 쏠림**: 상위 20종목을 업종으로 묶은 비중·대표(중앙값) 등락 — 요약 한 줄 → 막대 줄(신규 배지). 한국 = `/api/spine/kr/movers`(업종 → `/map?group=`), 미국 = 브리핑 스냅샷.
  - **③ 거래대금 상위**: 열 # · 종목(한국 = 급등락·신규 진입 배지 / 미국 = 티커 + 이름) · 업종(한국) 또는 실적(미국 — 이번 시즌 발표 종목이면 'M/D 실적 ›' → 콜 상세) · 등락(소수 2자리) · 거래대금. 좁은 화면은 종목 · 등락 · 거래대금 세 열.
  - **③ 가파른 추세**: 줄 = 이름(신고가 단계·신규 배지) / 업종 · 꾸준함 · ADX | 60일 추이 | 60일 수익률, 누르면 근거 창(`widgets/trend` `TrendEvidenceDialog`). '신고가·매물대' 보기는 `EventList`. 0종목이면 한 줄. **새 모멘텀 후보**: 새로 붙은 | 이어지는(`continuing`), 줄 = 티커 · 이름 · 발표일 / AI 요약 두 줄 → `?view=season&pick=`. 바닥 '실적 시즌 › 모멘텀 ›'.
  - **④ 국내 실적 시즌**(`/api/spine/transcript/season/kr`): 발표 · 업종보다 강했다 · 이번 주 발표 · 마감 D-n → 업종별 반응(발표 수 · 업종보다 강한 비율 막대 · 초과 중앙 %p) → 곧 발표 칩. 이번 시즌 공시가 없으면 한 줄 + '지난 시즌 마감 결과 보기 ›'. **미국 실적 시즌**: 판정 4칸(발표 · 업종보다 강했다 · 상회에도 약세 · 첫 반응 뒤집힘) → 이번 시즌 시장이 따진 것(요약 있는 섹터 전부, 줄 = 섹터 상세 링크) → 곧 발표 칩(오늘 · D-n). 시즌 판정은 `lib/seasonPhase`(`windows[].first~last`), 시즌 사이엔 '다음 실적 시즌까지 D-n' + 지난 시즌 정리 · 곧 발표 · 팔로우 기업 · 그 사이 볼 것을 칸 안 스크롤로. 팔로우 0이면 '기본 세트 팔로우'. 개발 서버에서만 `?today=`.
  - **④ 기업활동**: 원공시만(정정 제외), 줄 = 날짜 | 기업(보유·관심 배지) + 유형 / 한 줄 설명(D-306, 없으면 공시명 → DART). 보기 전체 | 내 그룹 | 유무증 Pro(공시 유형·정정 필터 칩은 두지 않는다). **최근 컨콜**: 지난 7일 받은 콜을 발표일 순, 줄 = 날짜 · 티커 · 회사 · 'Q3 FY26'.
  - **⑤ 개인 투자 열기**: 국면 배지 + 근거 두 개 → 값이 있는 지표(값 · 5년 백분위 막대 · 백분위), '추이 보기 ›'(/retail). **수출입**: 수출 총액(통계월이 늦으면 'n월 기준' 칩, `lib/trade` `tradeIsLagging`) · 기여 1위 → 산업별 수출 규모 상위 12(급등·급감 수).
  - 블록 상태: 데이터 전에는 칸 높이 그대로 뼈대(`FillSkeleton`), 오류는 그 칸만 `BlockError`, 빈 상태는 목록 자리 한 줄(`FillNote`). 머리 회색 줄은 데이터 전에도 같은 폭의 보이지 않는 자리.
  - **지수·요약 지표 API 계약**(`models/market_overview.py`): `MarketOverview { market; indices: IndexOverview[]; tiles: OverviewTile[] }`. `IndexOverview { key; name; value; change; change_pct; prev_close; session { state: pre|open|closed; trade_date; last_time(현지); last_kst; open; close }; ranges: { key: 1d|1m|3m|1y; base; points: {t, v}[] }[] }` — 1d 점은 `index_intraday` 현지 'HH:MM', 마감 뒤엔 저장 종가를 마감 시각 점으로 붙인다. 기간 점은 `market_indicators` `index_*` 일봉 21·63·250개(끝 점 = 1일 값), `base`는 그 앞 값(없으면 null). 전일 종가는 저장 일봉. `OverviewTile { key; label; value; change_pct; as_of; series(20); up/down/flat; buy/sell; growth_20; pctile; second }` — 없는 값은 null로 모양을 같게. 외부 호출 0, 시장 폭만 10분 메모(따뜻할 때 수 ms, 테스트 100ms 미만).
  - **장중 경로 수집**: `pipeline/index_intraday` + `scripts/index_intraday.py`, launchd `indexintraday` 10분 — 국장 09:00–15:30 KST · 미장 09:30–16:00 ET(+20분)에만 yfinance 5분봉 5콜, 장 밖·주말은 외부 호출 없이 끝. 공휴일 달력은 없다(그날 봉이 없으면 아무것도 저장하지 않음).
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

(2026-11-06 D-325: 대만 공급망이 카드 벽으로 바뀌어 `explore.twRevenue`·`explore.twLinks`를 목록에서 뺐다 — [tw-revenue](tw-revenue.md) 4-1.)

| id | 이름 | 원천 | 쓰는 곳 | 내용 |
|---|---|---|---|---|
| market.indices | 지수 띠 | `/indices` | 대시보드 | 지수별 값·등락 · 1Y 스파크 가로 띠 |
| market.context | 시장 요약 | `/macro` | 대시보드 | 환율·금리·유가·금·BTC 가로 띠 · 올리면 추이 차트(`MetricTrend`) |
| market.us | Market Overnight | `/us/briefing` | 대시보드 | `UsBriefingSection embedded` 전체(핵심 요약 bullet 먼저)를 칸 안에서 스크롤 |
| market.today | Market Today | `/spine/market-today` | 대시보드 | 회차 칩·텔레그램/뉴스 건수·다음 정리 시각 · 화두 — docs/specs/market-today.md |
| risk.regime | 시장 국면 | `/market-regime` | 대시보드 | 국장·미장 포스처 · 근거 한 줄 |
| risk.curve · risk.vix · risk.fear · risk.hy | 금리차 · VIX · 공포·탐욕 · HY | `/risk?range=3m&keys=curve,vix,fear_greed,hy` | 대시보드 | 값 · 20일 변화 · 3개월 스파크, 늦거나 실패하면 마지막 값 흐리게 + 기준 날짜 |
| world.changes | 이번 주 바뀐 서사 | `/spine/world/changes?days=7` | 대시보드 | 최근 7일 새 버전 · 옮겨 간 내용 1~2문장 |
| portfolio.today · portfolio.events · portfolio.flow | 포트폴리오 오늘 · 다가오는 일정 · 보유 종목 자료 흐름 | `/portfolio`·`/portfolio/history` · `/portfolio/events` · `/portfolio/flow` | 내 종목(보유 보기) | 비율·날짜만(D-212) |
| watch.digests | 관심 종목 오늘 요약 | `/spine/groups/{id}/digests` | 내 종목(전체 보기) | 최신 요약일 · 종목별 '새로운 점' 또는 첫 줄 |

종목 추적 카드 본문(`widgets/tracker`의 `TrackerBody`)은 섹션 목록에 없고 내 종목 화면의 '조건 편집' 시트가 직접 쓴다.

한국·미국 시장 탭은 섹션 목록을 쓰지 않고 칸을 직접 그린다(위 §0 공통 틀, 2026-11-06에 `explore.trend`·`explore.calls`·`explore.momentum` 정의를 걷었다).

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
