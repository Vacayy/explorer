import { QueryState } from "@/components/shared/QueryState"
import { Link, Navigate, useLocation } from 'react-router-dom'
import { ChevronRight, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader, PageLayout } from '@/components/shared/PageLayout'
import AreaSeriesChart from '@/components/charts/AreaSeriesChart'
import { TransactionDialog } from '@/components/portfolio/TransactionDialog'
import { TransactionSheet } from '@/components/portfolio/TransactionSheet'
import { ExposureCard } from '@/components/portfolio/ExposureCard'
import { EventsCard } from '@/components/portfolio/EventsCard'
import { PrinciplesCard } from '@/components/portfolio/PrinciplesCard'
import { PrincipleStateCard } from '@/components/portfolio/PrincipleStateCard'
import { AlertHistoryCard } from '@/components/portfolio/AlertHistoryCard'
import { HoldingsTab } from '@/components/portfolio/HoldingsTab'
import { useAutoRefreshPortfolioQuotes, usePortfolio, usePortfolioAlerts, usePortfolioHistory, usePrincipleState, useRefreshPortfolioQuotes } from '@/hooks/usePortfolio'
import { InfoTip } from '@/components/shared/InfoTip'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { formatNumber, formatPercent, formatRatio } from '@/utils/format'
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
    <div className="@container/portfolio surface-stack">
      {tab === 'principles' ? <>
          <PrincipleStateCard live={!!quoted} />
          <PrinciplesCard />
          <AlertHistoryCard />
        </>
        : tab === 'events' ? (empty ? <EmptyLedger /> : <EventsCard />)
        : <QueryState query={summary} loading={<><Skeleton className="h-28 w-full rounded-card" /><Skeleton className="h-64 w-full rounded-card" /></>} isEmpty={() => false}>{(data) => (empty ? <EmptyLedger />
        : tab === 'holdings' ? <HoldingsTab data={data} />
        : <Overview data={data} />)}</QueryState>}
    </div>
  </PageLayout>
}

function EmptyLedger() {
  return <Card><CardContent className="space-y-2 py-12 text-center"><p className="font-medium">아직 기록된 거래가 없습니다.</p>
    <p className="text-sm text-muted-foreground">우측 상단 ‘거래 입력’에서 입금 또는 매수를 기록하면 비중·수익률을 계산합니다.</p></CardContent></Card>
}

/** 개요. 폰(<768, ia-redesign §4.32): 원칙 줄 → 요약 2×2(계좌 수익률·오늘·현금 비중·보유) → 비중 막대 + 목록 → 최근 알림 3건. 수익률 추이·공통 변수는 넓은 화면에서만 */
function Overview({ data }: { data: PortfolioSummary }) {
  const held = data.holdings.length
  return <>
    <PrincipleLine live={!!data.quoted_at} />
    <Card><CardContent className="grid grid-cols-2 gap-3 py-3 @2xl/portfolio:grid-cols-5">
      {([['계좌 수익률', formatPercent(data.total_return_pct), tone(data.total_return_pct), ''],
        ['오늘', formatPercent(data.day_return_pct), tone(data.day_return_pct), ''],
        ['실현 손익', formatPercent(data.realized_pct), tone(data.realized_pct), 'max-md:hidden'],
        ['미실현 손익', formatPercent(data.unrealized_pct), tone(data.unrealized_pct), 'max-md:hidden'],
        ['현금 비중', formatRatio(data.cash_weight_pct), '', ''],
        ['보유', `${formatNumber(held)}종목`, '', 'md:hidden']] as const).map(([label, value, cls, show]) =>
        <div key={label} className={show}>
          <p className="flex items-center text-caption text-muted-foreground">{label}
            {label === '계좌 수익률' && <InfoTip label="수익률 계산 방법">계좌 수익률은 입출금 영향을 뺀 시간가중 수익률입니다. 실현·미실현 손익은 원금(입금 − 출금) 대비 비율입니다. 장중에는 보유 종목을 30분마다 실시간 시세로 다시 평가하고, 16:10 종가 수집 뒤에는 종가로 바뀝니다.</InfoTip>}</p>
          <p className={`mt-1 text-2xl font-semibold tabular-nums ${cls}`}>{value}</p></div>)}
    </CardContent></Card>

    <div className="surface-grid grid @3xl/portfolio:grid-cols-[280px_minmax(0,1fr)]">
      <Card><CardHeader><CardTitle>비중</CardTitle></CardHeader><CardContent><WeightPie data={data} /></CardContent></Card>
      <div className="max-md:hidden"><ReturnHistory live={!!data.quoted_at} /></div>
    </div>

    <RecentAlerts />
    <div className="max-md:hidden"><ExposureCard holdings={data.holdings} /></div>
  </>
}

/** 폰 원칙 줄 — 어기는 규칙이 없으면 한 줄, 있으면 그 자리에 규칙·종목 */
function PrincipleLine({ live }: { live: boolean }) {
  const state = usePrincipleState(live)
  const d = state.data
  if (!d) return null
  const bad = d.items.length > 0
  return <Link to="/portfolio/principles" className={cn('flex min-h-11 items-center gap-2 border px-3 py-2 text-sm md:hidden', bad ? 'border-down/40' : 'bg-muted/40')}>
    <Badge variant="outline" className={cn('shrink-0 text-[10px]', bad ? 'text-down' : 'text-fact border-fact/40')}>{bad ? '위반' : '지킴'}</Badge>
    <span className="min-w-0 flex-1 truncate">{bad ? d.items.map(v => v.message).join(' · ') : d.rules ? `어기고 있는 원칙 없음 · 수치 규칙 ${formatNumber(d.rules)}개` : '점검할 수치 규칙이 아직 없습니다'}</span>
    <span className="flex shrink-0 items-center text-muted-foreground">원칙<ChevronRight className="size-3.5" aria-hidden="true" /></span>
  </Link>
}

const ALERT_KIND: Record<string, string> = { day: '급등락', avg: '평단 구간', tech: '기술적 신호', disc: '공시', summary: '마감 요약', 'track-day': '추적 급등락', 'track-cond': '추적 조건' }

/** 폰 최근 알림 3건 — 전체는 원칙 탭 '알림 이력' */
function RecentAlerts() {
  const alerts = usePortfolioAlerts(14)
  const items = (alerts.data ?? []).slice(0, 3)
  return <Card className="md:hidden"><CardHeader><CardTitle>최근 알림</CardTitle></CardHeader><CardContent className="space-y-2">
    <QueryState query={alerts} loading={<Skeleton className="h-24 w-full" />} isEmpty={() => false}>{() => (!items.length ? <p className="text-sm text-muted-foreground">최근 14일 보낸 알림이 없습니다.</p>
      : <ul className="divide-y">{items.map((a, i) => <li key={`${a.sent_at}-${a.kind}-${i}`} className="grid grid-cols-[auto_1fr] gap-x-3 py-2">
          <span className="font-mono text-caption tabular-nums text-muted-foreground">{a.sent_at.slice(5, 16)}</span>
          <span className="min-w-0 text-sm">{a.name && <span className="font-medium">{a.name} · </span>}{a.label}
            <span className="block text-caption text-muted-foreground">{ALERT_KIND[a.kind] ?? a.kind}</span></span>
        </li>)}</ul>)}</QueryState>
    <Link to="/portfolio/principles" className="flex min-h-10 items-center text-sm font-medium">알림 전체<ChevronRight className="size-3.5" aria-hidden="true" /></Link>
  </CardContent></Card>
}

function WeightPie({ data }: { data: PortfolioSummary }) {
  const slices = [...data.holdings.map(h => ({ code: h.code, name: h.name, value: h.weight_pct ?? 0 })),
    ...(data.cash_weight_pct ? [{ code: '', name: '현금', value: data.cash_weight_pct }] : [])].filter(s => s.value > 0)
  const color = (s: { code: string }, i: number) => s.code ? `var(${COLORS[i % COLORS.length]})` : 'var(--muted-foreground)'
  return <div className="space-y-3">
    {/* 폰: 원 대신 한 줄 막대 */}
    <div className="flex h-2.5 overflow-hidden rounded-full bg-muted md:hidden" aria-hidden="true">
      {slices.map((s, i) => <span key={s.name} style={{ width: `${s.value}%`, background: color(s, i) }} />)}
    </div>
    <div className="h-48 max-md:hidden"><ResponsiveContainer><PieChart>
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
    {!data.holdings.length && <p className="text-sm text-muted-foreground md:hidden">보유 종목이 없습니다. <Link to="/portfolio/holdings" className="inline-flex min-h-10 items-center text-foreground hover:underline">청산 내역<ChevronRight className="size-3.5" aria-hidden="true" /></Link></p>}
  </div>
}

function ReturnHistory({ live }: { live: boolean }) {
  const history = usePortfolioHistory(live)
  const points = history.data ?? []
  return <Card><CardHeader><CardTitle>계좌 수익률 추이</CardTitle></CardHeader><CardContent>
    <QueryState query={history} loading={<Skeleton className="h-56 w-full" />} isEmpty={() => false}>{() => (points.length < 2 ? <p className="py-8 text-center text-sm text-muted-foreground">
          {points.length ? `${points[0].date} 시작 · ${formatPercent(points[0].cum_return_pct)}. 거래일이 쌓이면 매일 종가로 추이를 그립니다.` : '추이를 그릴 거래가 없습니다.'}</p>
      : <AreaSeriesChart data={points.map(p => ({ time: p.date, value: p.cum_return_pct }))} height={220} formatValue={v => formatPercent(v)} />)}</QueryState>
  </CardContent></Card>
}
