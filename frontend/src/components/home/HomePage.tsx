import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { IndexStrip } from "@/components/home/IndexStrip"
import { AiActivityFeed } from "@/components/home/AiActivityFeed"
import { RiskMonitoring } from '@/components/home/RiskMonitoring'
import { RetailHeatCard } from '@/components/home/RetailHeatCard'
import { MarketRegime } from "@/components/home/MarketRegime"
import { MacroLiquidity } from "@/components/home/MacroLiquidity"
import { UsBriefingSection } from "@/components/home/UsBriefingSection"
import { KrMoversSection } from "@/components/home/KrMoversSection"
import { ChannelReader } from "@/components/feed/ChannelReader"
import Dashboard from "@/components/home/Dashboard"
import { useHomeMode } from "@/hooks/useHomeMode"

/** 홈 › 대시보드(위젯) 또는 캔버스 › 피드(소스 디렉터리 + 리더). 보기는 URL home_view만 따른다. */
export default function HomePage() {
  const mode = useHomeMode()
  if (mode === 'feed') return (
    <PageLayout mode="reader" header={<PageHeader title="피드" />} overview={<AiActivityFeed />}>
      <ChannelReader />
    </PageLayout>
  )
  return <PageLayout mode="document" header={<PageHeader title="홈" />}><Dashboard /></PageLayout>
}

/** 홈 › 시장 브리핑 — 미국장·국장 전체 보기 (위젯 '전체 보기' 대상) */
export function HomeBriefingPage() {
  return <PageLayout mode="document" header={<PageHeader title="시장 브리핑" />} overview={<IndexStrip />}>
    <div className="@container/market space-y-5"><UsBriefingSection /><KrMoversSection /></div>
  </PageLayout>
}

/** 홈 › 국면·리스크 — 시장 국면·Risk 추이·개인 투자 열기 전체 보기 */
export function HomeRiskPage() {
  return <PageLayout mode="document" header={<PageHeader title="국면·리스크" />}>
    <div className="@container/market space-y-5"><MarketRegime /><RiskMonitoring /><RetailHeatCard /></div>
  </PageLayout>
}

/** 홈 › 매크로 — 매크로·유동성 지표와 신호등 전체 보기 (시장 요약 띠의 '상세'와 같은 카드) */
export function HomeMacroPage() {
  return <PageLayout mode="document" header={<PageHeader title="매크로" />}>
    <div className="@container/market space-y-5"><MacroLiquidity /></div>
  </PageLayout>
}
