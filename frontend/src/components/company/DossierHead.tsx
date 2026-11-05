import type { ReactNode } from 'react'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { formatPercent, formatStockPrice } from '@/utils/format'
import { shortDate, type LastClose } from '@/lib/dossier'

/**
 * 종목 도시에 머리(국내·미국 공용, ia-redesign §4.9) — 시장·업종 줄 · 이름 · 마지막 종가(전일 대비·기준일) · 동작.
 * 가격은 차트와 같은 저장 시세에서 온다(lib/dossier lastClose).
 */
export function DossierHead({ eyebrow, name, last, market, loading, actions }: {
  eyebrow: ReactNode
  name: string
  last: LastClose | null
  market: 'kr' | 'us'
  loading?: boolean
  actions?: ReactNode
}) {
  return (
    <header className="flex min-w-0 flex-wrap items-end justify-between gap-3" data-dossier-head>
      <div className="min-w-0">
        <p className="text-caption text-muted-foreground">{eyebrow}</p>
        <h1 className="mt-1 break-words text-page font-semibold">{name}</h1>
        {loading ? <Skeleton className="mt-2 h-7 w-48" />
          : last ? (
            <p className="mt-1 flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-2xl tabular-nums">{formatStockPrice(last.close, market)}</span>
              <span className={cn('font-mono text-sm tabular-nums', last.changePct == null ? 'text-muted-foreground' : last.changePct > 0 ? 'text-up' : last.changePct < 0 ? 'text-down' : '')}>
                {formatPercent(last.changePct)}
              </span>
              <span className="text-caption text-muted-foreground">{shortDate(last.date)} 종가</span>
            </p>
          ) : <p className="mt-1 text-sm text-muted-foreground">-</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export interface Metric { label: string; value: ReactNode; sub?: ReactNode }

/** 핵심 지표 띠 — 넓은 화면 한 줄, 모바일 3×2 (Mobile-Dossier) */
export function MetricStrip({ items, loading }: { items: Metric[]; loading?: boolean }) {
  return (
    <Card className="grid grid-cols-3 gap-0 py-0 lg:grid-flow-col lg:auto-cols-fr lg:grid-cols-none" aria-label="핵심 지표" data-dossier-metrics>
      {items.map((m) => (
        <div key={m.label} className="min-w-0 border-b border-r px-3 py-3 last:border-r-0 max-lg:[&:nth-child(3n)]:border-r-0 lg:border-b-0">
          <p className="truncate text-caption text-muted-foreground">{m.label}</p>
          <div className="mt-1 break-words font-mono text-base tabular-nums sm:text-lg">{loading ? <Skeleton className="h-6 w-20" /> : m.value}</div>
          {m.sub && !loading && <p className="mt-0.5 text-caption text-muted-foreground">{m.sub}</p>}
        </div>
      ))}
    </Card>
  )
}
