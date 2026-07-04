import HyperliquidSection from "./HyperliquidSection"
import PolymarketSection from "./PolymarketSection"

export default function OnchainPage() {
  return (
    <div className="space-y-6">
      <HyperliquidSection />
      <PolymarketSection />
    </div>
  )
}
