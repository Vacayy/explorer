import { Link } from "react-router-dom"
import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { AiActivityFeed } from "@/components/home/AiActivityFeed"
import { RiskMonitoring } from '@/components/home/RiskMonitoring'
import { RetailHeatCard } from '@/components/home/RetailHeatCard'
import { MarketRegime } from "@/components/home/MarketRegime"
import { MacroLiquidity } from "@/components/home/MacroLiquidity"
import { UsBriefingSection } from "@/components/home/UsBriefingSection"
import { HomeSection } from "@/components/home/HomeSection"
import HomeDashboard from "@/components/home/HomeDashboard"
import { ChannelReader } from "@/components/feed/ChannelReader"
import { QueryState } from "@/components/shared/QueryState"
import { Skeleton } from "@/components/ui/skeleton"
import { useDefaultWatchGroup } from "@/hooks/useGroups"
import { useHomeMode } from "@/hooks/useHomeMode"

/**
 * 홈 L2 = 시스템 고정 탭 다섯 개 (docs/specs/home-widgets.md §0): 대시보드 · 한국 시장 · 미국 시장 · 매크로 · 내 종목.
 * 한국·미국·매크로·내 종목은 이행 중 화면 — 기존 위젯 본문·카드를 섹션으로 모아 둔 것이고 3b~3d 단계에서 시안대로 바꾼다.
 * /home?home_view=feed는 피드(소스 디렉터리 + 리더)다. 보기는 URL home_view만 따른다.
 */
export default function HomePage() {
  const mode = useHomeMode()
  if (mode === 'feed') return (
    <PageLayout mode="reader" header={<PageHeader title="피드" />} overview={<AiActivityFeed />}>
      <ChannelReader />
    </PageLayout>
  )
  return <HomeDashboard />
}

/** 홈 › 한국 시장 (이행 중, 3b에서 시안 Home-KR로) — 가파른 추세 | 국장 거래대금, 수출입, 개인 투자 열기. 대만은 산업 › 대만 공급망 화면이 생길 때까지 여기 둔다 */
export function HomeKrPage() {
  return <PageLayout mode="document" header={<PageHeader title="한국 시장" />}>
    <div className="@container/market">
      <div className="surface-grid grid lg:grid-cols-2">
        <HomeSection widget="explore.trend" w={6} h={9} className="h-[560px]" />
        <HomeSection widget="market.kr" w={6} h={9} className="h-[560px]" />
      </div>
      <HomeSection widget="explore.trade" w={12} h={5} />
      <div id="retail" className="scroll-mt-4"><RetailHeatCard /></div>
      <div className="surface-grid grid lg:grid-cols-2">
        <HomeSection widget="explore.twRevenue" w={6} h={6} className="h-[440px]" />
        <HomeSection widget="explore.twLinks" w={6} h={6} className="h-[440px]" />
      </div>
    </div>
  </PageLayout>
}

/** 홈 › 미국 시장 (이행 중, 3b에서 시안 Home-US로) — 컨콜·실적 발표 | 실적 모멘텀, 어젯밤 미국장 브리핑 전문 */
export function HomeUsPage() {
  return <PageLayout mode="document" header={<PageHeader title="미국 시장" />}>
    <div className="@container/market space-y-0">
      <div className="surface-grid grid lg:grid-cols-2">
        <HomeSection widget="explore.calls" w={6} h={6} className="h-[420px]" />
        <HomeSection widget="explore.momentum" w={6} h={6} className="h-[420px]" />
      </div>
      <UsBriefingSection />
    </div>
  </PageLayout>
}

/** 홈 › 매크로 (이행 중, 3c에서 시안 Home-Macro로) — 매크로·유동성 + 옛 국면·리스크 화면(시장 국면·Risk 추이) */
export function HomeMacroPage() {
  return <PageLayout mode="document" header={<PageHeader title="매크로" />}>
    <div className="@container/market space-y-5"><MacroLiquidity /><MarketRegime /><RiskMonitoring /></div>
  </PageLayout>
}

/** 홈 › 내 종목 (이행 중, 3d에서 시안 Home-Stocks로) — 추적 표시 종목의 추적 카드 + 관심·보유 요약 */
export function HomeStocksPage() {
  const group = useDefaultWatchGroup()
  const loading = <div className="grid lg:grid-cols-2">{[0, 1].map(n => <Skeleton key={n} className="h-[480px] rounded-[var(--radius-card)]" />)}</div>
  return <PageLayout mode="document" header={<PageHeader title="내 종목" />}>
    <div className="@container/market">
      <QueryState query={group} loading={loading} isEmpty={() => false}>{g => {
        const tracked = g.members.filter(m => m.tracked)
        if (!g.members.length) return <p className="border p-6 text-sm text-muted-foreground">관심 종목이 없어요. <Link to="/follow/stocks" className="text-foreground underline-offset-4 hover:underline">종목 묶음에서 추가하기 ›</Link></p>
        if (!tracked.length) return <p className="border p-6 text-sm text-muted-foreground">추적 중인 종목이 없어요. <Link to={`/follow/stocks?group=${g.id}`} className="text-foreground underline-offset-4 hover:underline">관심 종목에서 추적 켜기 ›</Link></p>
        return <div className="surface-grid grid lg:grid-cols-2">
          {tracked.map(m => <HomeSection key={m.stock_code} widget="track.stock" params={{ code: m.stock_code, name: m.name }} w={6} h={8} bodyClassName="p-0" className="h-[560px]" />)}
        </div>
      }}</QueryState>
      <div className="surface-grid grid md:grid-cols-2 lg:grid-cols-3">
        <HomeSection widget="watch.signals" w={4} h={4} />
        <HomeSection widget="watch.digests" w={4} h={4} />
        <HomeSection widget="portfolio.today" w={4} h={4} />
        <HomeSection widget="portfolio.events" w={4} h={4} />
        <HomeSection widget="portfolio.flow" w={4} h={4} />
      </div>
    </div>
  </PageLayout>
}
