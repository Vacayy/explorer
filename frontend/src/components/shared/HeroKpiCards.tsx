import { memo } from "react"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber } from "@/utils/format"
import type { KpiData } from "@/hooks/useKpi"

interface Props {
  data: KpiData
}

export default function HeroKpiCards({ data }: Props) {
  const cards: KpiCardProps[] = [
    {
      label: "현재가",
      value: data.close ? `${formatNumber(data.close)}원` : "-",
      sub: data.price_change_pct != null
        ? `${data.price_change_pct > 0 ? "▲" : data.price_change_pct < 0 ? "▼" : ""}${data.price_change_pct > 0 ? "+" : ""}${data.price_change_pct.toFixed(2)}%`
        : undefined,
      subColor: data.price_change_pct != null
        ? data.price_change_pct > 0 ? "text-red-600" : data.price_change_pct < 0 ? "text-blue-600" : "text-muted-foreground"
        : undefined,
    },
    {
      label: "시가총액",
      value: data.market_cap ? formatKrw(data.market_cap) : "-",
    },
    {
      label: "PER",
      value: data.per ? `${data.per.toFixed(1)}배` : "-",
      sub: data.latest_year ? `${data.latest_year}Y 기준` : undefined,
    },
    {
      label: "PBR",
      value: data.pbr ? `${data.pbr.toFixed(2)}배` : "-",
    },
    {
      label: "영업이익률",
      value: data.op_margin != null ? `${data.op_margin.toFixed(1)}%` : "-",
      sub: data.op_margin_change != null
        ? `${data.op_margin_change > 0 ? "▲" : "▼"}${Math.abs(data.op_margin_change).toFixed(1)}%p`
        : undefined,
      subColor: data.op_margin_change != null
        ? data.op_margin_change > 0 ? "text-red-600" : "text-blue-600"
        : undefined,
    },
    {
      label: "ROE",
      value: data.roe != null ? `${data.roe.toFixed(1)}%` : "-",
      sub: data.roe_change != null
        ? `${data.roe_change > 0 ? "▲" : "▼"}${Math.abs(data.roe_change).toFixed(1)}%p`
        : undefined,
      subColor: data.roe_change != null
        ? data.roe_change > 0 ? "text-red-600" : "text-blue-600"
        : undefined,
    },
  ]

  return (
    <div className="grid grid-cols-6 gap-3">
      {cards.map((card) => (
        <KpiCard key={card.label} {...card} />
      ))}
    </div>
  )
}

interface KpiCardProps {
  label: string
  value: string
  sub?: string
  subColor?: string
}

const KpiCard = memo(function KpiCard({ label, value, sub, subColor }: KpiCardProps) {
  return (
    <Card className="p-4 text-center">
      <div className="text-xs text-muted-foreground font-medium mb-1">{label}</div>
      <div className="text-lg font-bold tabular-nums">{value}</div>
      {sub && (
        <div className={cn("text-xs mt-0.5 font-medium", subColor || "text-muted-foreground")}>
          {sub}
        </div>
      )}
    </Card>
  )
})
