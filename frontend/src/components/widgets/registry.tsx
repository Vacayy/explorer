import type { RiskCardKind } from "@/components/home/RiskMonitoring"
import type { SizeSpec, WidgetBodyProps, WidgetDef } from "./types"
import {
  ContextBody, IndicesBody, KrBody, RegimeBody, RetailBody, RiskBody, RiskDetail, UsBody,
  useContextMeta, useIndicesMeta, useKrMeta, useRegimeMeta, useRetailMeta, useRiskMeta, useUsMeta,
} from "./market"
import { MarketTodayBody, useMarketTodayMeta } from "./marketToday"
import { EXPLORE_WIDGETS } from "./explore"
import { PORTFOLIO_WIDGETS } from "./portfolio"
import { CANVAS_WIDGETS } from "./canvas"
import { WORLD_WIDGETS } from "./world"
import { PROXY_WIDGETS } from "./proxy"
import { TW_WIDGETS } from "./twRevenue"
import { TRACKER_WIDGETS } from "./tracker"
import { REGIME_WIDGETS } from "./regimes"

const risk = (id: string, metric: string, card: RiskCardKind, title: string, description: string): WidgetDef => ({
  id, title, description, section: "home", group: "국면·리스크", size: { w: 4, h: 3, minW: 3, minH: 2 },
  detailPath: "/home/macro", useMeta: () => useRiskMeta(metric),
  Body: (p: WidgetBodyProps) => <RiskBody {...p} metric={metric} />,
  Detail: () => <RiskDetail kind={card} />,
})

/** 위젯 목록 — 홈 고정 탭 섹션(home/HomeSection)이 id로 본문·기준 시각·전체 보기 경로를 빌려 쓴다 (home-widgets.md §0) */
export const WIDGETS: readonly WidgetDef[] = [
  { id: "market.indices", title: "지수 띠", description: "코스피·코스닥·S&P·나스닥·항셍·니케이·대만", section: "home", group: "시장",
    size: { w: 12, h: 1, minW: 6, minH: 1 }, flat: true, useMeta: useIndicesMeta, Body: IndicesBody },
  { id: "market.context", title: "시장 요약", description: "환율·미 2Y·10Y·유가·금·BTC", section: "home", group: "시장",
    size: { w: 12, h: 1, minW: 6, minH: 1 }, flat: true, detailPath: "/home/macro", useMeta: useContextMeta, Body: ContextBody },
  { id: "market.us", title: "Market Overnight", description: "어젯밤 미국장 · 거래대금 쏠림 · 매크로·기업 이슈 · 개별 급등락", section: "home", group: "시장 브리핑",
    size: { w: 6, h: 9, minW: 4, minH: 2 }, detailPath: "/home/us", useMeta: useUsMeta, Body: UsBody },
  { id: "market.today", title: "Market Today", description: "오늘 장중 · 3시간마다 텔레그램·뉴스에서 주로 나온 얘기", section: "home", group: "시장 브리핑",
    size: { w: 6, h: 9, minW: 3, minH: 2 }, useMeta: useMarketTodayMeta, Body: MarketTodayBody },
  { id: "market.kr", title: "전일 국장 거래대금", description: "거래대금 상위 · 섹터 쏠림 · 급등락", section: "home", group: "시장 브리핑",
    size: { w: 6, h: 9, minW: 4, minH: 2 }, detailPath: "/home/kr", useMeta: useKrMeta, Body: KrBody },
  { id: "risk.regime", title: "시장 국면", description: "국장·미장 포스처 · 공포탐욕·VIX", section: "home", group: "국면·리스크",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/home/macro", useMeta: useRegimeMeta, Body: RegimeBody },
  risk("risk.curve", "curve", "curve", "금리차 10Y−2Y", "장단기 금리차 · 20일 변화 · 3개월 추이"),
  risk("risk.vix", "vix", "vix", "VIX", "변동성 지수 · 20일 변화 · 3개월 추이"),
  risk("risk.fear", "fear_greed", "fear", "공포·탐욕", "CNN 0–100 · 20일 변화 · 3개월 추이"),
  risk("risk.hy", "hy", "credit", "HY 스프레드", "하이일드 OAS · 20일 변화 · 3개월 추이"),
  { id: "retail.heat", title: "개인 투자 열기 Δ", description: "20일 새 백분위가 가장 크게 움직인 지표", section: "home", group: "국면·리스크",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/home/kr#retail", useMeta: useRetailMeta, Body: RetailBody },
  // 영역별 위젯 — 각 파일에서만 더한다(병렬 작업 충돌 방지)
  ...EXPLORE_WIDGETS,
  ...TW_WIDGETS,
  ...PORTFOLIO_WIDGETS,
  ...CANVAS_WIDGETS,
  ...WORLD_WIDGETS,
  ...PROXY_WIDGETS,
  ...TRACKER_WIDGETS,
  ...REGIME_WIDGETS,
]

export const WIDGET_BY_ID: Record<string, WidgetDef> = Object.fromEntries(WIDGETS.map(w => [w.id, w]))
export const WIDGET_SIZES: Record<string, SizeSpec> = Object.fromEntries(WIDGETS.map(w => [w.id, w.size]))
