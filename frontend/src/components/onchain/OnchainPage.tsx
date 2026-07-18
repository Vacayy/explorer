import HyperliquidSection from "./HyperliquidSection"
import PolymarketSection from "./PolymarketSection"
import { PageContainer } from '@/components/shared/PageContainer'

export default function OnchainPage() {
  return (
    <PageContainer>
      <HyperliquidSection />
      <PolymarketSection />
    </PageContainer>
  )
}
