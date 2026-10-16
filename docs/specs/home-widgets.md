# 홈 위젯 대시보드

- 상태: P4 구현 계약 (2026-10-16). [home-feed](home-feed.md)의 Home 시장 탭 구성을 대체한다. 피드 리더는 캔버스 › 피드로 남는다.
- 셸: [app-shell](app-shell.md). 홈 L2 = 대시보드 · 시장 브리핑 · 국면·리스크 · 매크로.
- P4 범위: 위젯 틀·격자·추가 창·프리셋·서버 저장 + 시장 위젯 10종. 탐색·포트폴리오·캔버스·월드모델 위젯은 각 단계(P5~P7)에서 같은 계약으로 추가한다.

## 1. 화면

```
홈
[대시보드] 시장 브리핑  국면·리스크  매크로
프리셋 [기본 | 디레버리징 | 수출 사이클 | 이벤트 장세]        [편집] [+ 위젯 추가]
┌ 지수 띠 ─────────────────────────────────────────────┐
┌ 시장 요약 ───────────────────────────────────────────┐
┌ 어젯밤 미국장 ────────┐┌ 전일 국장 거래대금 ─────────┐
┌ 시장 국면 ──┐┌ Risk·금리차 ┐┌ Risk·VIX ┐┌ Risk·공포탐욕 ┐
```

- 격자: `react-grid-layout` v2, 12열, 행 높이 72px, 간격 12px. 폭 1024~1279px도 12열(셸이 1024 미만을 막는다).
- 편집 모드에서만 끌기(머리의 ⋮⋮ 손잡이)·크기 조절(오른쪽 아래 모서리)·삭제(×). 평소엔 고정 — 실수로 움직이지 않게.
- 위젯 추가: shadcn Dialog + Command(검색) + Tabs(홈·탐색·포트폴리오·캔버스·월드모델). 항목 = 이름·한 줄 설명·추가/추가됨. 아직 위젯이 없는 탭은 "다음 단계에서 추가됩니다"를 보인다.
- 프리셋을 고르면 현재 배치를 대체하기 전에 확인한다(AlertDialog).
- 시장 브리핑·국면·리스크·매크로 탭 = 지금 Home 카드 전체 보기(`/home/briefing`, `/home/risk`, `/home/macro`). 위젯 ⋮의 '전체 보기'가 이 탭으로 간다.

## 2. 위젯 계약

```ts
interface WidgetDef {
  id: string                         // 'market.us'
  title: string
  description: string                // 추가 창 한 줄
  section: SectionKey                // 추가 창 탭
  group: string                      // 추가 창 묶음
  size: { w: number; h: number; minW: number; minH: number }
  detailPath?: string                // '전체 보기'
  Body: React.FC<{ w: number; h: number }>   // 크기에 반응
}
```

1. **캐시된 GET만**: 위젯 본문은 기존 GET 훅(`useMacro`·`useMarketRegime`·`useKrMovers`·`useUsBriefing`·`useRiskWindow`·`useRetailSummary`·지수)만 쓴다. 갱신 버튼(POST)은 전체 보기 탭에만 둔다.
2. **기준 시각 = 원천 시각**: 머리 오른쪽에 응답의 `as_of`·`trade_date`·`fetched_at`. 서버 현재 시각을 쓰지 않는다.
3. **5-state + 원천 고장**: Loading=Skeleton, Error=다시 시도, Empty=정상적으로 비어 있음 문구, 원천 고장(`degraded`·`status!=ok`·`stale_days>1`)은 머리 시각을 주의 색으로 + 본문 첫 줄에 이유.
4. **요약층**: 큰 숫자 1개 + 한 줄 해석 + 목록·스파크라인. 크기가 작으면(h≤2) 큰 숫자와 한 줄만.
5. **원천 하나**: 금리·VIX·공포탐욕은 정본(`risk_*`, D-236)만 읽는다.

## 3. 시장 위젯 10종 (P4)

| id | 이름 | 원천 | 기본 크기 | 큰 숫자 · 한 줄 · 목록 |
|---|---|---|---|---|
| market.indices | 지수 띠 | `/indices` | 12×1 | 지수별 값·등락 가로 띠 |
| market.context | 시장 요약 | `/macro` | 12×1 | 환율·금리·유가·금·BTC 가로 띠 |
| market.us | 어젯밤 미국장 | `/us/briefing` | 6×4 | 최대 쏠림 섹터 비중 · 종합 첫 문장 · 개별 이슈 3 |
| market.kr | 전일 국장 거래대금 | `/kr/movers` | 6×4 | 최대 쏠림 섹터 비중 · 섹터 중앙 등락 · 상위 5 막대 |
| risk.regime | 시장 국면 | `/market-regime` | 6×3 | 국장·미장 포스처 · 근거 한 줄 · 공포탐욕·VIX 타일 |
| risk.curve | 금리차 10Y−2Y | `/risk?range=3m&keys=curve,vix,fear_greed,hy` | 3×3 | 값 · 20일 변화 · 3개월 스파크 |
| risk.vix | VIX | 〃 | 3×3 | 〃 |
| risk.fear | 공포·탐욕 | 〃 | 3×3 | 〃 |
| risk.hy | HY 스프레드 | 〃 | 3×3 | 〃 |
| retail.heat | 개인 투자 열기 Δ | `/retail` | 6×3 | 20일 백분위 변화가 가장 큰 지표 · 국면 · 나머지 지표 |

### 포트폴리오·관심 위젯 6종 (P6c, `widgets/portfolio.tsx`)

비율·날짜만(D-212). `/api/portfolio`는 저장된 시세만 읽는다(갱신 POST는 포트폴리오 화면에만). 묶음 위젯은 기본 관심 묶음(`/spine/groups/default-watch`)을 쓴다. 위젯별 묶음 선택(`params`)은 위젯 틀이 아직 `params`를 본문에 넘기지 않아 다음 단계로 미룬다.

| id | 이름 | 원천 | 크기 | 기준 시각 · 큰 숫자 · 한 줄 · 목록 |
|---|---|---|---|---|
| portfolio.today | 포트폴리오 오늘 | `/portfolio`, `/portfolio/history` | 4×3 | 장중 시세 시각/종가일 · 오늘 % · 누적 TWR·현금 비중 · 누적 수익률 스파크 |
| portfolio.events | 다가오는 일정 | `/portfolio/events` | 4×4 | (없음) · 다음 일정 D-n · 제목(예상 표시) · 다음 일정 목록 |
| portfolio.exposure | 공통 변수 노출 | `/portfolio/exposure` | 4×3 | 비중 기준일 · 최대 노출 % · 변수명·방향 · 상위 3 막대 |
| portfolio.flow | 보유 종목 자료 흐름 | `/portfolio/flow` | 4×3 | 집계일 · 급증+부정 전환 건수 · 각 건수 · 종목별 배지·오늘 언급 |
| watch.signals | 묶음 오늘 신호 | `/spine/groups/{id}/signals?days=1` | 4×3 | 마지막 평가일(최신 거래일 평가 전이면 주의 색) · 새 신호 수 · 종목·조건 |
| watch.digests | 관심 종목 오늘 요약 | `/spine/groups/{id}/digests` | 4×4 | 최신 요약일 · 그날 요약 종목 수 · 종목별 '새로운 점' 또는 첫 줄 |

## 4. 저장

`GET/PUT /api/dashboard/layouts/home` — `{items: [{i, widget, x, y, w, h, params}]}`. 없으면(404) '기본' 프리셋. 편집을 끝낼 때 한 번 저장한다(끌 때마다 저장하지 않음). 저장 실패는 토스트 + 편집 상태 유지. 알 수 없는 widget id는 렌더하지 않고 다음 저장에서 빠진다.

## 5. 프리셋

| 프리셋 | 위젯 |
|---|---|
| 기본 | 지수 띠 · 시장 요약 · 미국장 · 국장 · 금리차 · VIX · 공포탐욕 · HY · 국면 · 개인 열기 |
| 디레버리징 | 지수 띠 · 개인 열기 · HY · 금리차 · VIX · 공포탐욕 · 국면 |
| 수출 사이클 | 지수 띠 · 국장 · 미국장 · 시장 요약 (P6에서 Trade Pulse·섹터 이동 추가) |
| 이벤트 장세 | 지수 띠 · 미국장 · 국장 · 국면 (P6에서 기업활동·유무증 추가) |

## 6. 검증

`tsc`, FE 테스트(레이아웃 정규화: 알 수 없는 위젯 제거·크기 하한·중복 id), 백엔드 레이아웃 API 테스트(기존), 실제 화면: 기본 배치 렌더·편집 끌기/크기/삭제·추가 창·저장 후 새로고침 유지·프리셋 확인 창·전체 보기 탭 3개.
