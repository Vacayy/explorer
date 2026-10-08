import { useSearchParams } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { PageHeader, PageLayout } from '@/components/shared/PageLayout'
import { ErrorState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import AreaSeriesChart from '@/components/charts/AreaSeriesChart'
import { TransactionDialog } from '@/components/portfolio/TransactionDialog'
import { TransactionSheet } from '@/components/portfolio/TransactionSheet'
import { HoldingDetail } from '@/components/portfolio/HoldingDetail'
import { ExposureCard } from '@/components/portfolio/ExposureCard'
import { EventsCard } from '@/components/portfolio/EventsCard'
import { usePortfolio, usePortfolioHistory, useRefreshPortfolioQuotes } from '@/hooks/usePortfolio'
import { formatNumber, formatPercent, formatRatio } from '@/utils/format'
import type { PortfolioSummary } from '@/types'

const COLORS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5']
const tone = (v: number | null | undefined) => v == null || v === 0 ? '' : v > 0 ? 'text-up' : 'text-down'

/** 포트폴리오(D-212) — 비율 전용. 원화 금액은 입력 폼 밖 어디에도 나오지 않는다. */
export default function PortfolioPage() {
  const summary = usePortfolio()
  const refresh = useRefreshPortfolioQuotes()
  const quoted = summary.data?.quoted_at
  const basis = quoted ? `장중 ${quoted.slice(11, 16)} 시세 · 30분마다 갱신` : summary.data?.as_of ? `${summary.data.as_of} 종가 기준` : ''
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
      {summary.isPending ? <><Skeleton className="h-28 w-full rounded-xl" /><Skeleton className="h-64 w-full rounded-xl" /></>
        : summary.isError ? <ErrorState message={summary.error.message} onRetry={() => void summary.refetch()} />
        : !summary.data.holdings.length && summary.data.cash_weight_pct == null
          ? <Card><CardContent className="space-y-2 py-12 text-center"><p className="font-medium">아직 기록된 거래가 없습니다.</p>
              <p className="text-sm text-muted-foreground">우측 상단 ‘거래 입력’에서 입금 또는 매수를 기록하면 비중·수익률을 계산합니다.</p></CardContent></Card>
          : <Overview data={summary.data} />}
    </div>
  </PageLayout>
}

function Overview({ data }: { data: PortfolioSummary }) {
  const [sp, setSp] = useSearchParams()
  const selected = data.holdings.find(h => h.code === sp.get('stock')) ?? data.holdings[0]
  return <>
    <Card><CardContent className="grid grid-cols-3 gap-3 py-4">
      {([['계좌 수익률', formatPercent(data.total_return_pct), tone(data.total_return_pct)],
        ['오늘', formatPercent(data.day_return_pct), tone(data.day_return_pct)],
        ['현금 비중', formatRatio(data.cash_weight_pct), '']] as const).map(([label, value, cls]) =>
        <div key={label}><p className="text-caption text-muted-foreground">{label}</p><p className={`mt-1 text-2xl font-semibold tabular-nums ${cls}`}>{value}</p></div>)}
      <p className="col-span-3 text-caption text-muted-foreground">계좌 수익률은 입출금 영향을 뺀 시간가중 수익률입니다. 장중에는 보유 종목을 30분마다 실시간 시세로 다시 평가하고, 16:10 종가 수집 뒤에는 종가로 바뀝니다.</p>
    </CardContent></Card>

    <div className="grid gap-4 @3xl/portfolio:grid-cols-[280px_minmax(0,1fr)]">
      <Card><CardHeader><CardTitle>비중</CardTitle></CardHeader><CardContent><WeightPie data={data} /></CardContent></Card>
      <Card><CardHeader><CardTitle>보유 종목</CardTitle></CardHeader><CardContent>
        <Table><TableHeader><TableRow>
          <TableHead>종목</TableHead><TableHead className="text-right">비중</TableHead><TableHead className="text-right">평단</TableHead>
          <TableHead className="text-right">현재가</TableHead><TableHead className="text-right">수익률</TableHead><TableHead className="text-right">전일비</TableHead>
        </TableRow></TableHeader><TableBody>
          {data.holdings.map(h => <TableRow key={h.code} className="cursor-pointer" onClick={() => setSp(prev => { const n = new URLSearchParams(prev); n.set('stock', h.code); return n }, { replace: true })}>
            <TableCell className="font-medium">{h.name}</TableCell>
            <TableCell className="text-right tabular-nums">{formatRatio(h.weight_pct)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatNumber(Math.round(h.avg_price))}</TableCell>
            <TableCell className="text-right tabular-nums">{h.last_close == null ? '-' : formatNumber(h.last_close)}
              {h.price_source === 'live' && h.quoted_at && <span className="block text-caption text-muted-foreground">장중 {h.quoted_at.slice(11, 16)}</span>}</TableCell>
            <TableCell className={`text-right tabular-nums ${tone(h.return_pct)}`}>{formatPercent(h.return_pct)}</TableCell>
            <TableCell className={`text-right tabular-nums ${tone(h.day_change_pct)}`}>{formatPercent(h.day_change_pct)}</TableCell>
          </TableRow>)}
          <TableRow><TableCell className="text-muted-foreground">현금</TableCell><TableCell className="text-right tabular-nums">{formatRatio(data.cash_weight_pct)}</TableCell><TableCell colSpan={4} /></TableRow>
        </TableBody></Table>
      </CardContent></Card>
    </div>

    <div className="grid gap-4 @5xl/portfolio:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <ExposureCard holdings={data.holdings} />
      <EventsCard />
    </div>

    <ReturnHistory live={!!data.quoted_at} />

    {selected && <section className="space-y-3">
      <SegmentTabs tabs={data.holdings.map(h => ({ value: h.code, label: h.name }))} value={selected.code}
        onChange={code => setSp(prev => { const n = new URLSearchParams(prev); n.set('stock', code); return n }, { replace: true })} />
      <HoldingDetail key={selected.code} holding={selected} />
    </section>}
  </>
}

function WeightPie({ data }: { data: PortfolioSummary }) {
  const slices = [...data.holdings.map(h => ({ name: h.name, value: h.weight_pct ?? 0 })),
    ...(data.cash_weight_pct ? [{ name: '현금', value: data.cash_weight_pct }] : [])].filter(s => s.value > 0)
  return <div className="space-y-3">
    <div className="h-48"><ResponsiveContainer><PieChart>
      <Pie data={slices} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="90%" stroke="var(--card)" isAnimationActive={false}>
        {slices.map((s, i) => <Cell key={s.name} fill={s.name === '현금' ? 'var(--muted-foreground)' : `var(${COLORS[i % COLORS.length]})`} />)}
      </Pie>
      <Tooltip formatter={v => formatRatio(Number(v))} />
    </PieChart></ResponsiveContainer></div>
    <ul className="space-y-1 text-sm">{slices.map((s, i) => <li key={s.name} className="flex items-center gap-2">
      <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: s.name === '현금' ? 'var(--muted-foreground)' : `var(${COLORS[i % COLORS.length]})` }} />
      <span className="min-w-0 flex-1 truncate">{s.name}</span><span className="tabular-nums">{formatRatio(s.value)}</span></li>)}</ul>
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
