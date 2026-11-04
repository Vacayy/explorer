import { Navigate, useLocation } from "react-router-dom"
import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { RetailHeatCard } from '@/components/home/RetailHeatCard'
import { UsBriefingSection } from "@/components/home/UsBriefingSection"
import { UsSeasonBlock } from "@/components/home/UsSeasonBlock"
import { KrTurnoverBlock } from "@/components/home/KrTurnoverBlock"
import { TradeBlock } from "@/components/home/TradeBlock"
import { HomeSection } from "@/components/home/HomeSection"
import HomeDashboard from "@/components/home/HomeDashboard"
import { getHomeMode } from "@/hooks/useHomeMode"
import { useIsMobile } from "@/hooks/use-mobile"

/**
 * 홈 L2 = 시스템 고정 탭 다섯 개 (docs/specs/home-widgets.md §0): 대시보드 · 한국 시장 · 미국 시장 · 매크로 · 내 종목.
 * 한국·미국 시장은 시안대로(3b), 매크로는 home/HomeMacroPage(3c), 내 종목은 home/HomeStocksPage(3d).
 * 옛 /home?home_view=feed는 피드 대메뉴(/feed)로 보낸다 — 나머지 쿼리(channel·channel_type·reader_topic …)는 그대로(ia-redesign §10.6).
 */
export default function HomePage() {
  const { search } = useLocation()
  if (getHomeMode(search) === 'feed') {
    const rest = new URLSearchParams(search)
    rest.delete('home_view')
    return <Navigate to={`/feed${rest.size ? `?${rest}` : ''}`} replace />
  }
  return <HomeDashboard />
}

/**
 * 홈 › 한국 시장 (시안 Home-KR, ia-redesign §4.2·§4.17) — 국장 거래대금 상위 | 가파른 추세(같은 높이) → 개인 투자 열기 → 수출입.
 * 대만 월매출·대만→한국 연결은 산업 › 대만 공급망 화면이 생길 때까지 맨 아래에 둔다(§10.4a 1단계 보류).
 */
export function HomeKrPage() {
  const mobile = useIsMobile()   // 좁은 화면은 추세 표를 좁은 열(종목·60일·수익률)로
  return <PageLayout mode="document" header={<PageHeader title="한국 시장" />}>
    <div className="@container/market">
      <div className="surface-grid grid lg:grid-cols-2">
        <KrTurnoverBlock />
        {/* 같은 높이 — 넓은 화면은 거래대금 칸 높이에 맞추고, 추세 표는 칸 안에서 스크롤 */}
        <div className="relative lg:min-h-[560px]"><HomeSection widget="explore.trend" w={mobile ? 4 : 6} h={9} className="h-[560px] lg:absolute lg:inset-0 lg:h-auto" /></div>
      </div>
      <div id="retail" className="scroll-mt-4"><RetailHeatCard /></div>
      <TradeBlock />
      <div className="surface-grid grid lg:grid-cols-2">
        <HomeSection widget="explore.twRevenue" w={6} h={6} className="h-[440px]" />
        <HomeSection widget="explore.twLinks" w={6} h={6} className="h-[440px]" />
      </div>
    </div>
  </PageLayout>
}

/**
 * 홈 › 미국 시장 (시안 Home-US, ia-redesign §4.3·§4.28) — 실적 시즌 블록(시즌 사이엔 다음 시즌까지 D-n) →
 * 어젯밤 미국장 브리핑 전문 | 거래대금 쏠림·개별 움직임 → 컨콜·실적 발표 | 실적 모멘텀(이행 화면에서 옮겨 온 것).
 */
export function HomeUsPage() {
  return <PageLayout mode="document" header={<PageHeader title="미국 시장" />}>
    <div className="@container/market">
      <UsSeasonBlock />
      <UsBriefingSection columns />
      <div className="surface-grid grid lg:grid-cols-2">
        <HomeSection widget="explore.calls" w={6} h={6} className="h-[420px]" />
        <HomeSection widget="explore.momentum" w={6} h={6} className="h-[420px]" />
      </div>
    </div>
  </PageLayout>
}
