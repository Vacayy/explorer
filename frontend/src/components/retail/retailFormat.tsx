import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatKrw, formatNumber, formatPercent, formatRatio } from '@/utils/format'
import type { RetailMetric, RetailRegimeKey } from '@/types'

/** 지표 값 — 변화율은 부호 %, 비중은 %, 금액은 억·조. */
export function metricValue(m: Pick<RetailMetric, 'unit' | 'value'>): string {
  if (m.value == null) return '-'
  return m.unit === 'rate' ? formatPercent(m.value * 100) : m.unit === 'ratio' ? formatRatio(m.value * 100) : formatKrw(m.value)
}

/** 5년 백분위 막대 — 80 이상 과열 = 상승색(--up, 따뜻한 쪽) · 20 이하 위축 = 하락색(--down, 차가운 쪽) · 그 사이 회색. 시안의 파랑·초록은 의미가 뒤집혀 쓰지 않는다(D-322). */
export function PctileBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-caption text-muted-foreground">-</span>
  const tone = value >= 80 ? 'bg-up' : value <= 20 ? 'bg-down' : 'bg-ink-2'
  return <span className="inline-flex items-center gap-1.5" title={`과거 5년 중 ${formatNumber(Math.round(value))}% 지점`}>
    <span className="h-1.5 w-[90px] overflow-hidden rounded-[3px] bg-chip max-sm:w-12" aria-hidden="true"><span className={`block h-full rounded-[3px] ${tone}`} style={{ width: `${value}%` }} /></span>
    <span className="w-7 text-right font-mono text-xs tabular-nums">{formatNumber(Math.round(value))}</span>
  </span>
}

const REGIME_TONE: Record<RetailRegimeKey, 'down' | 'up' | 'hyp' | 'warn' | 'neutral'> = {
  deleveraging: 'down', leverage_led: 'up', churn: 'hyp', broad_inflow: 'warn', neutral: 'neutral',
}
export function RegimeBadge({ regime, className = '' }: { regime: { key: RetailRegimeKey; label: string }; className?: string }) {
  return <Badge variant={REGIME_TONE[regime.key]} className={className}>{regime.label}</Badge>
}

const signTone = (v: number | null | undefined) => v == null || v === 0 ? 'text-ink-3' : v > 0 ? 'text-up-ink' : 'text-down-ink'

/** 지표 표 — 값 · 과거 5년 백분위 · 20일 전 대비 백분위 변화. 개인 투자 열기 화면과 홈 › 한국 시장이 같이 쓴다 */
export function MetricTable({ metrics }: { metrics: RetailMetric[] }) {
  return <div className="overflow-x-auto"><Table>
    <TableHeader><TableRow><TableHead>지표</TableHead><TableHead className="text-right">값</TableHead><TableHead>과거 5년 백분위</TableHead><TableHead className="text-right">20일 전 대비</TableHead></TableRow></TableHeader>
    <TableBody>{metrics.map(m => <TableRow key={m.key} className={m.value == null ? 'text-muted-foreground' : ''}>
      <TableCell className="whitespace-nowrap max-sm:min-w-32 max-sm:whitespace-normal max-sm:break-keep">{m.label}</TableCell>
      <TableCell className={`text-right font-mono tabular-nums ${m.unit === 'rate' ? signTone(m.value) : ''}`}>{metricValue(m)}</TableCell>
      <TableCell><PctileBar value={m.pctile} /></TableCell>
      <TableCell className={`text-right font-mono tabular-nums ${signTone(m.pctile_change)}`}>{m.pctile_change == null ? '-' : `${m.pctile_change > 0 ? '+' : ''}${formatNumber(Math.round(m.pctile_change))}`}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div>
}
