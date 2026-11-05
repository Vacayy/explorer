import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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
    <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted max-sm:w-12" aria-hidden="true"><span className={`block h-full rounded-full ${tone}`} style={{ width: `${value}%` }} /></span>
    <span className="w-8 text-right tabular-nums">{formatNumber(Math.round(value))}</span>
  </span>
}

const REGIME_TONE: Record<RetailRegimeKey, string> = {
  deleveraging: 'border-down/50 text-down-ink', leverage_led: 'border-up/50 text-up-ink', churn: 'border-hypothesis/50 text-hypothesis',
  broad_inflow: 'border-primary/50 text-primary', neutral: 'text-muted-foreground',
}
export function RegimeBadge({ regime, className = '' }: { regime: { key: RetailRegimeKey; label: string }; className?: string }) {
  return <Badge variant="outline" className={`font-medium ${REGIME_TONE[regime.key]} ${className}`}>{regime.label}</Badge>
}

/** 지표 표 — 값 · 과거 5년 백분위 · 20일 전 대비 백분위 변화. 개인 투자 열기 화면과 홈 › 한국 시장이 같이 쓴다 */
export function MetricTable({ metrics }: { metrics: RetailMetric[] }) {
  return <div className="overflow-x-auto"><Table>
    <TableHeader><TableRow><TableHead>지표</TableHead><TableHead className="text-right">값</TableHead><TableHead>과거 5년 백분위</TableHead><TableHead className="text-right">20일 전 대비</TableHead></TableRow></TableHeader>
    <TableBody>{metrics.map(m => <TableRow key={m.key} className={m.value == null ? 'text-muted-foreground' : ''}>
      <TableCell className="whitespace-nowrap max-sm:min-w-32 max-sm:whitespace-normal max-sm:break-keep">{m.label}</TableCell>
      <TableCell className="text-right tabular-nums">{metricValue(m)}</TableCell>
      <TableCell><PctileBar value={m.pctile} /></TableCell>
      <TableCell className="text-right tabular-nums text-muted-foreground">{m.pctile_change == null ? '-' : `${m.pctile_change > 0 ? '+' : ''}${formatNumber(Math.round(m.pctile_change))}`}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div>
}
