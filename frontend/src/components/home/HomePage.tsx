import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { IndexStrip } from "@/components/home/IndexStrip"
import { AiActivityFeed } from "@/components/home/AiActivityFeed"
import { RiskMonitoring } from '@/components/home/RiskMonitoring'
import { RetailHeatCard } from '@/components/home/RetailHeatCard'
import { MarketContext } from "@/components/home/MarketContext"
import { UsBriefingSection } from "@/components/home/UsBriefingSection"
import { KrMoversSection } from "@/components/home/KrMoversSection"
import { ChannelReader } from "@/components/feed/ChannelReader"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { useHomeMode } from "@/hooks/useHomeMode"

/** Full-width market overview or a source directory and article reader. */
export default function HomePage() {
  const { mode, setMode } = useHomeMode()
  return (
    <PageLayout mode={mode === 'feed' ? 'reader' : 'document'}
      header={<PageHeader title="Home" actions={<SegmentTabs tabs={[{ value: 'market', label: '시장' }, { value: 'feed', label: '피드' }]} value={mode} onChange={setMode} />} />}
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
