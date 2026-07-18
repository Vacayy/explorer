import { memo } from "react"
import { usePolymarket } from "@/hooks/useOnchain"
import type { PolymarketEvent } from "@/hooks/useOnchain"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import { formatUsd } from "@/utils/format"
import { SectionSkeleton, ErrorCard } from "./SectionSkeleton"

const EventCard = memo(function EventCard({ event }: { event: PolymarketEvent }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="font-medium text-sm mb-2 line-clamp-2">{event.title}</div>
      <div className="text-xs text-muted-foreground mb-3">
        총 거래량 {formatUsd(event.volume)}
      </div>
      <div className="space-y-2">
        {event.markets.slice(0, 3).map((m, i) => {
          const yesPercent = m.yesPrice != null ? m.yesPrice * 100 : null
          return (
            <div key={i} className="flex items-center gap-2">
              <div className="flex-1 min-w-0">
                <div className="text-xs truncate" title={m.question}>{m.question}</div>
              </div>
              {yesPercent != null && (
                <div className="flex items-center gap-1.5 shrink-0">
                  <Progress
                    value={Math.min(yesPercent, 100)}
                    className="w-16 h-1.5 [&>[data-slot=progress-indicator]]:bg-emerald-500"
                  />
                  <span className={cn(
                    "text-xs font-mono w-12 text-right",
                    yesPercent >= 50 ? "text-emerald-600" : "text-rose-500"
                  )}>
                    {yesPercent.toFixed(1)}%
                  </span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
})

export default function PolymarketSection() {
  const { data, isLoading, error } = usePolymarket()

  if (isLoading) return <SectionSkeleton title="Polymarket — Prediction Markets" />
  if (error) return <ErrorCard title="Polymarket" message="데이터를 불러올 수 없습니다." />
  if (!data) return null

  const categories = ["finance", "economy", "tech", "geopolitics"] as const
  const categoryLabels: Record<string, string> = {
    finance: "금융 (Finance)",
    economy: "경제 (Economy)",
    tech: "기술 (Tech)",
    geopolitics: "지정학 (Geopolitics)",
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          Polymarket — Prediction Markets
          <span className="text-xs font-normal text-muted-foreground">실시간 예측 시장</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {categories.map((cat) => {
            const category = data[cat]
            if (!category) return null
            return (
              <div key={cat}>
                <div className="text-sm font-semibold mb-3">{categoryLabels[cat]}</div>
                <div className="grid grid-cols-3 gap-3">
                  {category.events.map((event, i) => (
                    <EventCard key={i} event={event} />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
