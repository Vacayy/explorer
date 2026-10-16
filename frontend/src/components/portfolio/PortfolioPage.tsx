import { Link, Navigate, useLocation } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader, PageLayout } from '@/components/shared/PageLayout'
import { ErrorState } from '@/components/shared/ErrorState'
import AreaSeriesChart from '@/components/charts/AreaSeriesChart'
import { TransactionDialog } from '@/components/portfolio/TransactionDialog'
import { TransactionSheet } from '@/components/portfolio/TransactionSheet'
import { ExposureCard } from '@/components/portfolio/ExposureCard'
import { EventsCard } from '@/components/portfolio/EventsCard'
import { PrinciplesCard } from '@/components/portfolio/PrinciplesCard'
import { PrincipleStateCard } from '@/components/portfolio/PrincipleStateCard'
import { AlertHistoryCard } from '@/components/portfolio/AlertHistoryCard'
import { HoldingsTab } from '@/components/portfolio/HoldingsTab'
import { useAutoRefreshPortfolioQuotes, usePortfolio, usePortfolioHistory, useRefreshPortfolioQuotes } from '@/hooks/usePortfolio'
import { formatPercent, formatRatio } from '@/utils/format'
import type { PortfolioSummary } from '@/types'

const COLORS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5']
const tone = (v: number | null | undefined) => v == null || v === 0 ? '' : v > 0 ? 'text-up' : 'text-down'

/** L2 탭 = URL (docs/specs/portfolio-ledger.md §화면). 종목 묶음은 /follow/stocks */
export type PortfolioTab = 'overview' | 'holdings' | 'principles' | 'events'

/** 포트폴리오(D-212) — 비율 전용. 원화 금액은 입력 폼 밖 어디에도 나오지 않는다. 머리(시세 갱신·거래)는 모든 탭이 같다. */
export default function PortfolioPage({ tab = 'overview' }: { tab?: PortfolioTab }) {
  const { search } = useLocation()
  const summary = usePortfolio()
  const refresh = useRefreshPortfolioQuotes()
  useAutoRefreshPortfolioQuotes(!!summary.data?.holdings.length)
  // 옛 링크 /portfolio?stock= — 종목 상세는 보유 탭으로 옮겼다
  if (tab === 'overview' && new URLSearchParams(search).has('stock')) return <Navigate to={`/portfolio/holdings${search}`} replace />
  const quoted = summary.data?.quoted_at
  const basis = quoted ? `장중 ${quoted.slice(11, 16)} 시세 · 30분마다 갱신` : summary.data?.as_of ? `${summary.data.as_of} 종가 기준` : ''
  const empty = !!summary.data && !summary.data.holdings.length && summary.data.cash_weight_pct == null
  return <PageLayout header={<PageHeader title="포트폴리오" description={basis ? `${basis} · 비율만 표시` : '비율만 표시'}
    actions={<>
      <Button size="sm" variant="outline" disabled={refresh.isPending || !summary.data?.holdings.length}
        onClick={() => refresh.mutate(undefined, {
          onSuccess: r => r.quoted_at ? toast.success(`${r.quoted_at.slice(11, 16)} 시세로 갱신했습니다.`) : toast.error('시세를 받지 못했습니다.'),
          onError: e => toast.error(e.message),
        })}>
        <RefreshCw aria-hidden="true" className={refresh.isPending ? 'animate-spin' : ''} />시세 갱신</Button>
      <TransactionSheet /><TransactionDialog /></>} />}>
    <div className="@container/portfolio space-y-5">
      {tab === 'principles' ? <>
          <PrincipleStateCard live={!!quoted} />
          <PrinciplesCard />
          <AlertHistoryCard />
        </>
        : tab === 'events' ? (empty ? <EmptyLedger /> : <EventsCard />)
        : summary.isPending ? <><Skeleton className="h-28 w-full rounded-xl" /><Skeleton className="h-64 w-full rounded-xl" /></>
        : summary.isError ? <ErrorState message={summary.error.message} onRetry={() => void summary.refetch()} />
        : empty ? <EmptyLedger />
        : tab === 'holdings' ? <HoldingsTab data={summary.data} />
        : <Overview data={summary.data} />}
    </div>
  </PageLayout>
}

function EmptyLedger() {
  return <Card><CardContent className="space-y-2 py-12 text-center"><p className="font-medium">아직 기록된 거래가 없습니다.</p>
    <p className="text-sm text-muted-foreground">우측 상단 ‘거래 입력’에서 입금 또는 매수를 기록하면 비중·수익률을 계산합니다.</p></CardContent></Card>
}

function Overview({ data }: { data: PortfolioSummary }) {
  return <>
    <Card><CardContent className="grid grid-cols-2 gap-3 py-4 @2xl/portfolio:grid-cols-5">
      {([['계좌 수익률', formatPercent(data.total_return_pct), tone(data.total_return_pct)],
        ['오늘', formatPercent(data.day_return_pct), tone(data.day_return_pct)],
        ['실현 손익', formatPercent(data.realized_pct), tone(data.realized_pct)],
        ['미실현 손익', formatPercent(data.unrealized_pct), tone(data.unrealized_pct)],
        ['현금 비중', formatRatio(data.cash_weight_pct), '']] as const).map(([label, value, cls]) =>
        <div key={label}><p className="text-caption text-muted-foreground">{label}</p><p className={`mt-1 text-2xl font-semibold tabular-nums ${cls}`}>{value}</p></div>)}
      <p className="col-span-2 text-caption text-muted-foreground @2xl/portfolio:col-span-5">계좌 수익률은 입출금 영향을 뺀 시간가중 수익률입니다. 실현·미실현 손익은 원금(입금 − 출금) 대비 비율입니다. 장중에는 보유 종목을 30분마다 실시간 시세로 다시 평가하고, 16:10 종가 수집 뒤에는 종가로 바뀝니다.</p>
    </CardContent></Card>

    <div className="grid gap-4 @3xl/portfolio:grid-cols-[280px_minmax(0,1fr)]">
      <Card><CardHeader><CardTitle>비중</CardTitle></CardHeader><CardContent><WeightPie data={data} /></CardContent></Card>
      <ReturnHistory live={!!data.quoted_at} />
    </div>

    <ExposureCard holdings={data.holdings} />
  </>
}

function WeightPie({ data }: { data: PortfolioSummary }) {
  const slices = [...data.holdings.map(h => ({ code: h.code, name: h.name, value: h.weight_pct ?? 0 })),
    ...(data.cash_weight_pct ? [{ code: '', name: '현금', value: data.cash_weight_pct }] : [])].filter(s => s.value > 0)
  const color = (s: { code: string }, i: number) => s.code ? `var(${COLORS[i % COLORS.length]})` : 'var(--muted-foreground)'
  return <div className="space-y-3">
    <div className="h-48"><ResponsiveContainer><PieChart>
      <Pie data={slices} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="90%" stroke="var(--card)" isAnimationActive={false}>
        {slices.map((s, i) => <Cell key={s.name} fill={color(s, i)} />)}
      </Pie>
      <Tooltip formatter={v => formatRatio(Number(v))} />
    </PieChart></ResponsiveContainer></div>
    <ul className="space-y-1 text-sm">{slices.map((s, i) => <li key={s.name} className="flex items-center gap-2">
      <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: color(s, i) }} />
      {s.code ? <Link to={`/portfolio/holdings?stock=${s.code}`} className="min-w-0 flex-1 truncate hover:underline">{s.name}</Link>
        : <span className="min-w-0 flex-1 truncate">{s.name}</span>}
      <span className="tabular-nums">{formatRatio(s.value)}</span></li>)}</ul>
  </div>
}

function ReturnHistory({ live }: { live: boolean }) {
  const history = usePortfolioHistory(live)
  const points = history.data ?? []
  return <Card><CardHeader><CardTitle>계좌 수익률 추이</CardTitle></CardHeader><CardContent>
    {history.isPending ? <Skeleton className="h-56 w-full" />
      : history.isError ? <ErrorState onRetry={() => void history.refetch()} />
      : points.length < 2 ? <p className="py-8 text-center text-sm text-muted-foreground">
          {points.length ? `${points[0].date} 시작 · ${formatPercent(points[0].cum_return_pct)}. 거래일이 쌓이면 매일 종가로 추이를 그립니다.` : '추이를 그릴 거래가 없습니다.'}</p>
      : <AreaSeriesChart data={points.map(p => ({ time: p.date, value: p.cum_return_pct }))} height={220} formatValue={v => formatPercent(v)} />}
  </CardContent></Card>
}
