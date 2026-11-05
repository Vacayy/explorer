import type { CSSProperties } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { PageLayout } from "@/components/shared/PageLayout"
import { ErrorBoundary } from "@/components/shared/ErrorBoundary"
import { HomeBlock, HomeSection } from "@/components/home/HomeSection"
import { ContextBody, IndicesBody, RegimeBody, RiskTrend, useRegimeMeta } from "@/components/widgets/market"
import { useIndices, useKrBreadth } from "@/hooks/useDashboard"
import { formatKstLongDate } from "@/utils/format"

/**
 * 홈 › 대시보드 — 시스템 고정 화면 (docs/specs/home-widgets.md §0, ia-redesign §4.1).
 * 순서 고정: 기상도(날짜 · 지수 띠 · 시장 요약 띠) → Market Overnight | Market Today(같은 높이) → 이번 주 바뀐 서사 → 국면·리스크.
 * 사용자가 고르는 배치·편집·위젯 추가는 없다. 블록마다 따로 불러오고 따로 실패한다.
 * 분위기(그라디언트·세로 리브·유리 패널)는 이 상단 기상도에만 쓴다 (D-320).
 */
export default function HomeDashboard() {
  return (
    <PageLayout mode="document">
      <div className="@container/market flex flex-col gap-4">
        <WeatherHeader />

        {/* 같은 높이 두 칸(유리 패널, 1024 이상) — 넘치는 본문은 칸 안에서 스크롤, 그 아래 폭은 내용 높이. 기상도 아래쪽 분위기(베일)를 이어 쓴다 */}
        <section aria-label="브리핑" data-veil className="weather p-4 max-sm:p-3">
          <div className="grid gap-3.5 lg:grid-cols-2">
            <HomeSection widget="market.us" w={6} h={9} display link={{ to: "/home/us", label: "미국 시장" }} className={`${GLASS_PANEL} lg:h-[796px]`} />
            <HomeSection widget="market.today" w={6} h={9} display link={{ to: "/home/kr", label: "한국 시장" }} className={`${GLASS_PANEL} lg:h-[796px]`} />
          </div>
        </section>

        <div>
          <HomeSection widget="world.changes" w={12} h={3} />
          <RiskBlock />
        </div>
      </div>
    </PageLayout>
  )
}

const GLASS_PANEL = "glass rounded-[16px] [&>header]:border-line"

/**
 * 기상도 — 그라디언트 바탕 + 세로 리브 + 유리 패널(시안 Home). 분홍(상승)·파랑(하락) 비율(D-321):
 * 국내 시장 폭(최근 거래일 상승 종목 / 상승+하락) → 없으면 지수 띠의 상승 지수 비율 → 그것도 없으면 기본 0.33(시안 값).
 */
function WeatherHeader() {
  const client = useQueryClient()
  const { data } = useIndices()
  const { data: breadth } = useKrBreadth()
  const moved = (data?.items ?? []).filter(r => r.change_pct != null && r.change_pct !== 0)
  const ratio = breadth?.up_ratio ?? (moved.length ? moved.filter(r => r.change_pct! > 0).length / moved.length : null)
  const style = ratio == null ? undefined : { "--weather-up": ratio.toFixed(2) } as CSSProperties
  const reset = () => { void client.refetchQueries({ type: "active", predicate: q => q.state.status === "error" }) }
  return (
    <section aria-label="시장" data-weather-up={ratio ?? undefined} className="weather flex flex-col gap-3.5 pb-[18px]" style={style}>
      <div className="flex flex-wrap items-baseline justify-between gap-2.5 px-[22px] pt-[22px] max-sm:px-4 max-sm:pt-4">
        <h1 className="font-display text-[34px] leading-[1.15] font-light tracking-[-0.02em] max-sm:text-[28px]">{formatKstLongDate()}</h1>
      </div>
      <div data-home-section="market.indices" className="glass mx-[18px] min-h-[92px] overflow-hidden rounded-[14px] max-sm:mx-3">
        <ErrorBoundary onReset={reset}><IndicesBody w={12} h={2} /></ErrorBoundary>
      </div>
      <div data-home-section="market.context" className="glass mx-[18px] overflow-hidden rounded-[12px] max-sm:mx-3">
        <ErrorBoundary onReset={reset}><ContextBody w={12} h={2} /></ErrorBoundary>
      </div>
    </section>
  )
}

/**
 * 국면·리스크 — 한 칸(시안 Home): 상태 줄(국장·미장 포스처 칩 + 한 줄) → 지표 넷(3개월 회색 추이·20일 변화). 모바일은 VIX·공포탐욕만.
 * 포스처와 지표는 따로 불러오고 따로 실패한다.
 */
function RiskBlock() {
  const meta = useRegimeMeta()
  return (
    <section aria-label="국면·리스크">
      <HomeBlock label="risk" title="국면·리스크" info="국장·미장 포스처 · VIX · 공포·탐욕 · HY OAS · 장단기 금리차(3개월 추이·20일 변화)"
        asOf={meta.asOf} stale={meta.stale} link={{ to: "/home/macro", label: "매크로" }} bodyClassName="flex flex-col gap-2.5">
        <RegimeBody w={12} h={2} />
        <div className="grid grid-cols-2 gap-x-[18px] border-t lg:grid-cols-4">
          <RiskTrend metric="vix" label="VIX" />
          <RiskTrend metric="fear_greed" label="공포·탐욕" />
          <RiskTrend metric="hy" label="HY OAS" className="max-md:hidden" />
          <RiskTrend metric="curve" label="10Y − 2Y" className="max-md:hidden" />
        </div>
      </HomeBlock>
    </section>
  )
}
