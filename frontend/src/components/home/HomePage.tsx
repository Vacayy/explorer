import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { IndexStrip } from "@/components/home/IndexStrip"
import { AiActivityFeed } from "@/components/home/AiActivityFeed"
import { RiskMonitoring } from '@/components/home/RiskMonitoring'
import { RetailHeatCard } from '@/components/home/RetailHeatCard'
import { MarketContext } from "@/components/home/MarketContext"
import { UsBriefingSection } from "@/components/home/UsBriefingSection"
import { KrMoversSection } from "@/components/home/KrMoversSection"
import { ChannelReader } from "@/components/feed/ChannelReader"
import { useHomeMode } from "@/hooks/useHomeMode"

/** 홈 › 대시보드(시장) 또는 캔버스 › 피드(소스 디렉터리 + 리더). 보기는 URL home_view만 따른다. */
export default function HomePage() {
  const mode = useHomeMode()
  return (
    <PageLayout mode={mode === 'feed' ? 'reader' : 'document'}
      header={<PageHeader title={mode === 'feed' ? '피드' : '홈'} />}
      overview={mode === 'feed' ? <AiActivityFeed /> : <IndexStrip />}>
      {mode === 'feed' ? <ChannelReader /> : <div className="@container/market space-y-5">
        <MarketContext />
        <UsBriefingSection />
        <KrMoversSection />
        <RiskMonitoring />
        <RetailHeatCard />
      </div>}
    </PageLayout>
  )
}
