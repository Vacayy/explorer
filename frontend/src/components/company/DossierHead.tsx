import type { ReactNode } from 'react'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { InfoTip } from '@/components/shared/InfoTip'
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
              <span className={cn('font-mono text-sm tabular-nums', last.changePct == null ? 'text-muted-foreground' : last.changePct > 0 ? 'text-up-ink' : last.changePct < 0 ? 'text-down-ink' : '')}>
                {formatPercent(last.changePct)}
              </span>
              <span className="text-caption text-muted-foreground">{shortDate(last.date)} 종가</span>
            </p>
          ) : <p className="mt-1 text-sm text-muted-foreground">-</p>}
      </div>
      {/* 좁은 화면은 동작 줄을 처음부터 다음 줄에 — 종가가 늦게 와서 줄이 바뀌며 아래가 밀리지 않게 */}
      {actions && <div className="flex flex-wrap items-center gap-2 max-sm:w-full">{actions}</div>}
    </header>
  )
}

/** 지표가 어떻게 나왔는가 — ⓘ 툴팁에 공식·출처·기준 시점 순으로 보인다 */
export interface MetricSource { formula?: ReactNode; source: ReactNode; asOf?: ReactNode; note?: ReactNode }
export interface Metric { label: string; value: ReactNode; sub?: ReactNode; info?: MetricSource }

function SourceTip({ label, info }: { label: string; info: MetricSource }) {
  const rows: [string, ReactNode][] = [['공식', info.formula], ['출처', info.source], ['기준', info.asOf]]
  return (
    <InfoTip label={`${label} 산출 방법`} className="-my-1 size-5">
      <div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
          {rows.filter(([, v]) => v != null && v !== '').map(([k, v]) => (
            <div key={k} className="contents"><dt className="opacity-70">{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
        {info.note && <p className="mt-1 opacity-70">{info.note}</p>}
      </div>
    </InfoTip>
  )
}

/** 핵심 지표 띠 — 넓은 화면 한 줄, 모바일 3×2 (Mobile-Dossier) */
export function MetricStrip({ items, loading }: { items: Metric[]; loading?: boolean }) {
  return (
    <Card className="grid grid-cols-3 gap-0 py-0 lg:grid-flow-col lg:auto-cols-fr lg:grid-cols-none" aria-label="핵심 지표" data-dossier-metrics>
      {items.map((m) => (
        <div key={m.label} className="min-w-0 border-b border-r px-3 py-3 last:border-r-0 max-lg:[&:nth-child(3n)]:border-r-0 lg:border-b-0">
          <div className="flex h-[1.125rem] min-w-0 items-center gap-0.5">
            <p className="truncate text-caption text-muted-foreground">{m.label}</p>
            {m.info && <SourceTip label={m.label} info={m.info} />}
          </div>
          <div className="mt-1 break-words font-mono text-base tabular-nums sm:text-lg">{loading ? <Skeleton className="h-6 w-20" /> : m.value}</div>
          {/* 보조 줄 자리는 늘 둔다 — 불러온 뒤 한 칸에만 생기며 띠 높이가 바뀌지 않게 */}
          <p className="mt-0.5 text-caption text-muted-foreground">{!loading && m.sub ? m.sub : '\u00a0'}</p>
        </div>
      ))}
    </Card>
  )
}
