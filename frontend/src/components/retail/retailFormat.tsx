import { Badge } from '@/components/ui/badge'
import { formatKrw, formatNumber, formatPercent, formatRatio } from '@/utils/format'
import type { RetailMetric, RetailRegimeKey } from '@/types'

/** 지표 값 — 변화율은 부호 %, 비중은 %, 금액은 억·조. */
export function metricValue(m: Pick<RetailMetric, 'unit' | 'value'>): string {
  if (m.value == null) return '-'
  return m.unit === 'rate' ? formatPercent(m.value * 100) : m.unit === 'ratio' ? formatRatio(m.value * 100) : formatKrw(m.value)
}

/** 5년 백분위 막대 — 80 이상은 과열 쪽, 20 이하는 위축 쪽 색. */
export function PctileBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-caption text-muted-foreground">-</span>
  const tone = value >= 80 ? 'bg-up' : value <= 20 ? 'bg-down' : 'bg-muted-foreground/60'
  return <span className="inline-flex items-center gap-2" title={`과거 5년 중 ${formatNumber(Math.round(value))}% 지점`}>
    <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden="true"><span className={`block h-full rounded-full ${tone}`} style={{ width: `${value}%` }} /></span>
    <span className="w-8 text-right tabular-nums">{formatNumber(Math.round(value))}</span>
  </span>
}

const REGIME_TONE: Record<RetailRegimeKey, string> = {
  deleveraging: 'border-down/50 text-down', leverage_led: 'border-up/50 text-up', churn: 'border-hypothesis/50 text-hypothesis',
  broad_inflow: 'border-primary/50 text-primary', neutral: 'text-muted-foreground',
}
export function RegimeBadge({ regime, className = '' }: { regime: { key: RetailRegimeKey; label: string }; className?: string }) {
  return <Badge variant="outline" className={`font-medium ${REGIME_TONE[regime.key]} ${className}`}>{regime.label}</Badge>
}
