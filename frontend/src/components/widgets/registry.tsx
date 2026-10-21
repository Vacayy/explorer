import type { SectionKey } from "@/components/layout/navConfig"
import type { RiskCardKind } from "@/components/home/RiskMonitoring"
import type { SizeSpec, WidgetBodyProps, WidgetDef } from "./types"
import {
  ContextBody, IndicesBody, KrBody, RegimeBody, RetailBody, RiskBody, RiskDetail, UsBody,
  useContextMeta, useIndicesMeta, useKrMeta, useRegimeMeta, useRetailMeta, useRiskMeta, useUsMeta,
} from "./market"
import { EXPLORE_WIDGETS } from "./explore"
import { PORTFOLIO_WIDGETS } from "./portfolio"
import { CANVAS_WIDGETS } from "./canvas"
import { WORLD_WIDGETS } from "./world"
import { PROXY_WIDGETS } from "./proxy"
import { TW_WIDGETS } from "./twRevenue"
import { TRACKER_WIDGETS } from "./tracker"

const risk = (id: string, metric: string, card: RiskCardKind, title: string, description: string): WidgetDef => ({
  id, title, description, section: "home", group: "국면·리스크", size: { w: 4, h: 3, minW: 3, minH: 2 },
  detailPath: "/home/risk", useMeta: () => useRiskMeta(metric),
  Body: (p: WidgetBodyProps) => <RiskBody {...p} metric={metric} />,
  Detail: () => <RiskDetail kind={card} />,
})

/** 위젯 목록 — 추가 창·배치·프리셋의 단일 소스. 다른 L1의 위젯은 각 단계(P5~P7)에서 더한다 */
export const WIDGETS: readonly WidgetDef[] = [
  { id: "market.indices", title: "지수 띠", description: "코스피·코스닥·S&P·나스닥·항셍·니케이·대만", section: "home", group: "시장",
    size: { w: 12, h: 1, minW: 6, minH: 1 }, flat: true, useMeta: useIndicesMeta, Body: IndicesBody },
  { id: "market.context", title: "시장 요약", description: "환율·미 2Y·10Y·유가·금·BTC", section: "home", group: "시장",
    size: { w: 12, h: 1, minW: 6, minH: 1 }, flat: true, detailPath: "/home/macro", useMeta: useContextMeta, Body: ContextBody },
  { id: "market.us", title: "어젯밤 미국장", description: "거래대금 쏠림 · 매크로·기업 이슈 · 개별 급등락", section: "home", group: "시장 브리핑",
    size: { w: 6, h: 9, minW: 4, minH: 2 }, detailPath: "/home/briefing", useMeta: useUsMeta, Body: UsBody },
  { id: "market.kr", title: "전일 국장 거래대금", description: "거래대금 상위 · 섹터 쏠림 · 급등락", section: "home", group: "시장 브리핑",
    size: { w: 6, h: 9, minW: 4, minH: 2 }, detailPath: "/home/briefing", useMeta: useKrMeta, Body: KrBody },
  { id: "risk.regime", title: "시장 국면", description: "국장·미장 포스처 · 공포탐욕·VIX", section: "home", group: "국면·리스크",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/home/risk", useMeta: useRegimeMeta, Body: RegimeBody },
  risk("risk.curve", "curve", "curve", "금리차 10Y−2Y", "장단기 금리차 · 20일 변화 · 3개월 추이"),
  risk("risk.vix", "vix", "vix", "VIX", "변동성 지수 · 20일 변화 · 3개월 추이"),
  risk("risk.fear", "fear_greed", "fear", "공포·탐욕", "CNN 0–100 · 20일 변화 · 3개월 추이"),
  risk("risk.hy", "hy", "credit", "HY 스프레드", "하이일드 OAS · 20일 변화 · 3개월 추이"),
  { id: "retail.heat", title: "개인 투자 열기 Δ", description: "20일 새 백분위가 가장 크게 움직인 지표", section: "home", group: "국면·리스크",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/home/risk", useMeta: useRetailMeta, Body: RetailBody },
  // 영역별 위젯 — 각 파일에서만 더한다(병렬 작업 충돌 방지)
  ...EXPLORE_WIDGETS,
  ...TW_WIDGETS,
  ...PORTFOLIO_WIDGETS,
  ...CANVAS_WIDGETS,
  ...WORLD_WIDGETS,
  ...PROXY_WIDGETS,
  ...TRACKER_WIDGETS,
]

export const WIDGET_BY_ID: Record<string, WidgetDef> = Object.fromEntries(WIDGETS.map(w => [w.id, w]))
export const WIDGET_SIZES: Record<string, SizeSpec> = Object.fromEntries(WIDGETS.map(w => [w.id, w.size]))

/** 시스템 프리셋 — 새 메뉴를 만들 때 고르는 출발점(home-widgets.md §5). 만든 뒤엔 그 메뉴의 배치일 뿐이다 */
export const SYSTEM_PRESETS: readonly { key: string; label: string; description: string; widgets: string[] }[] = [
  { key: "base", label: "기본", description: "지수·시장 맥락·미국장·국장·리스크 지표", widgets: ["market.indices", "market.context", "market.us", "market.kr", "risk.curve", "risk.vix", "risk.fear", "risk.hy", "risk.regime", "retail.heat"] },
  { key: "briefing", label: "시장 브리핑", description: "지수와 미국장·국장 움직임", widgets: ["market.indices", "market.context", "market.us", "market.kr"] },
  { key: "risk", label: "국면·리스크", description: "시장 국면·개인 과열·금리차·VIX·HY", widgets: ["risk.regime", "retail.heat", "risk.curve", "risk.vix", "risk.fear", "risk.hy"] },
  { key: "macro", label: "매크로", description: "시장 맥락·금리차·HY·회사채·수출입", widgets: ["market.context", "market.indices", "risk.curve", "risk.hy", "explore.credit", "explore.trade"] },
  { key: "portfolio", label: "보유 점검", description: "오늘 보유 종목·일정·수급·노출", widgets: ["portfolio.today", "portfolio.events", "portfolio.flow", "portfolio.exposure"] },
  { key: "delever", label: "디레버리징", description: "신용 경색·변동성 신호 모아 보기", widgets: ["market.indices", "risk.hy", "risk.curve", "risk.vix", "risk.fear", "retail.heat", "risk.regime"] },
  { key: "export", label: "수출 사이클", description: "수출입·섹터 이동·회사채", widgets: ["market.indices", "explore.trade", "explore.sectorShift", "market.kr", "market.us", "explore.credit"] },
  { key: "event", label: "이벤트 장세", description: "기업활동·권리·인물 이벤트", widgets: ["market.indices", "market.us", "market.kr", "risk.regime", "explore.actions", "explore.rights", "explore.people"] },
]

/** 추가 창 탭 순서 — 위젯이 아직 없는 탭은 '다음 단계' 안내 */
export const GALLERY_SECTIONS: readonly { key: SectionKey; label: string }[] = [
  { key: "home", label: "홈" }, { key: "explore", label: "탐색" }, { key: "portfolio", label: "포트폴리오" },
  { key: "canvas", label: "캔버스" }, { key: "world", label: "월드모델" },
]
