import type { WidgetBodyProps, WidgetDef } from "./types"
import {
  ContextBody, IndicesBody, RegimeBody, RiskBody, UsBody,
  useContextMeta, useIndicesMeta, useRegimeMeta, useRiskMeta, useUsMeta,
} from "./market"
import { MarketTodayBody, useMarketTodayMeta } from "./marketToday"
import { PORTFOLIO_WIDGETS } from "./portfolio"
import { WORLD_WIDGETS } from "./world"
import { TW_WIDGETS } from "./twRevenue"

const risk = (id: string, metric: string, title: string, description: string): WidgetDef => ({
  id, title, description, detailPath: "/home/macro", useMeta: () => useRiskMeta(metric),
  Body: (p: WidgetBodyProps) => <RiskBody {...p} metric={metric} />,
})

/** 섹션 목록 — 홈 고정 탭 섹션(home/HomeSection)이 id로 본문·기준 시각·전체 보기 경로를 빌려 쓴다 (home-widgets.md §0) */
const WIDGETS: readonly WidgetDef[] = [
  { id: "market.indices", title: "지수 띠", description: "코스피·코스닥·S&P·나스닥·항셍·니케이·대만", useMeta: useIndicesMeta, Body: IndicesBody },
  { id: "market.context", title: "시장 요약", description: "환율·미 2Y·10Y·유가·금·BTC", detailPath: "/home/macro", useMeta: useContextMeta, Body: ContextBody },
  { id: "market.us", title: "Market Overnight", description: "어젯밤 미국장 · 거래대금 쏠림 · 매크로·기업 이슈 · 개별 급등락",
    detailPath: "/home/us", useMeta: useUsMeta, Body: UsBody },
  { id: "market.today", title: "Market Today", description: "오늘 장중 · 3시간마다 텔레그램·뉴스에서 주로 나온 얘기", useMeta: useMarketTodayMeta, Body: MarketTodayBody },
  { id: "risk.regime", title: "시장 국면", description: "국장·미장 포스처 · 공포탐욕·VIX", detailPath: "/home/macro", useMeta: useRegimeMeta, Body: RegimeBody },
  risk("risk.curve", "curve", "금리차 10Y−2Y", "장단기 금리차 · 20일 변화 · 3개월 추이"),
  risk("risk.vix", "vix", "VIX", "변동성 지수 · 20일 변화 · 3개월 추이"),
  risk("risk.fear", "fear_greed", "공포·탐욕", "CNN 0–100 · 20일 변화 · 3개월 추이"),
  risk("risk.hy", "hy", "HY 스프레드", "하이일드 OAS · 20일 변화 · 3개월 추이"),
  // 영역별 섹션 — 각 파일에서만 더한다
  ...TW_WIDGETS,
  ...PORTFOLIO_WIDGETS,
  ...WORLD_WIDGETS,
]

export const WIDGET_BY_ID: Record<string, WidgetDef> = Object.fromEntries(WIDGETS.map(w => [w.id, w]))
