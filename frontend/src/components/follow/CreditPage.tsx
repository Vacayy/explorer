import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import { PageLayout } from '@/components/shared/PageLayout'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import MultiLineChart from '@/components/charts/MultiLineChart'
import { HomeBlock } from '@/components/home/HomeSection'
import { SummaryStrip, SummaryStripSkeleton } from '@/components/industry/SummaryStrip'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useCreditHistory, useCreditTable } from '@/hooks/useCredit'
import { useChartPalette } from '@/hooks/useChartPalette'
import { useIsMobile } from '@/hooks/use-mobile'
import { bySpread, creditGroupMedians, defaultCreditPicks, parseCreditRange, sliceByRange } from '@/lib/credit'
import { cn } from '@/lib/utils'
import { formatBp, formatNumber, formatRatio, formatYield } from '@/utils/format'
import type { CreditRow } from '@/types'

const MAX_SELECTED = 6
const TOP = 14
const tone = (v: number | null) => v == null || v === 0 ? 'text-muted-foreground' : v > 0 ? 'text-up-ink' : 'text-down-ink'   // 스프레드 확대 = 빨강

/**
 * 산업 › 회사채 (/follow/credit, 시안 Industry-Credit, ia-redesign §4.8c · D-230, docs/specs/credit-spreads.md).
 * 요약 줄 → 스프레드 비교 차트(최대 6곳, 수익률/스프레드, 3개월·1년·전체) → 종목별 스프레드(넓은 순 14, 전체 보기) | 그룹별 중앙값.
 * URL: credit(고른 회사, 없으면 1개월 확대 상위 2 — 1개월 변화가 비면 스프레드 넓은 순), credit_view, credit_range, credit_all.
 */
export default function CreditPage() {
  const [params, setParams] = useSearchParams()
  const table = useCreditTable()
  const rows = useMemo(() => table.data?.rows ?? [], [table.data])
  const selected = (params.get('credit')?.split(',').filter(t => t && t !== '-') ?? defaultCreditPicks(rows)).slice(0, MAX_SELECTED)
  const set = (key: string, value: string | null) => setParams(prev => { const n = new URLSearchParams(prev); if (value) n.set(key, value); else n.delete(key); return n }, { replace: true, preventScrollReset: true })
  const toggle = (ticker: string) => set('credit', (selected.includes(ticker) ? selected.filter(t => t !== ticker) : [...selected, ticker].slice(-MAX_SELECTED)).join(',') || '-')

  if (table.isPending) return <PageLayout mode="document"><div className="flex flex-col"><SummaryStripSkeleton /><Skeleton className="h-[420px] w-full rounded-card" /><Skeleton className="h-96 w-full rounded-card" /></div></PageLayout>
  if (table.isError) return <PageLayout mode="document"><ErrorState message="회사채 스프레드를 불러오지 못했습니다." onRetry={() => void table.refetch()} /></PageLayout>
  const data = table.data
  const priced = rows.filter(r => r.spread_bp != null)
  if (!priced.length) return <PageLayout mode="document"><EmptyState message="아직 수집된 회사채가 없습니다. 매일 07:30에 수집합니다." /></PageLayout>
  const widest = [...priced].sort(bySpread)[0]

  return <PageLayout mode="document">
    <div className="flex flex-col">
      <SummaryStrip label="credit" cells={[
        { label: '관측 회사채', value: formatNumber(priced.length), sub: data.as_of ?? '-' },
        { label: '하이일드 등급', value: formatNumber(rows.filter(r => r.hy).length) },
        { label: '가장 넓은 스프레드', value: `${formatBp(widest.spread_bp)}bp`, sub: widest.name },
        { label: '그룹', value: formatNumber(data.groups.length), sub: 'AI 투자 자금 흐름 순' },
      ]} />
      <SpreadChart rows={rows} selected={selected} view={params.get('credit_view') === 'yield' ? 'yield' : 'spread'}
        range={parseCreditRange(params.get('credit_range'))} onParam={set} onToggle={toggle} />
      <div className="@container"><div className="surface-grid grid @min-[68rem]:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <SpreadTable rows={rows} asOf={data.as_of} groups={data.groups} all={params.get('credit_all') === '1'}
          onAll={v => set('credit_all', v ? '1' : null)} selected={selected} onToggle={toggle} />
        <HomeBlock label="credit.groups" title={<>그룹별 <span className="ml-1 text-xs font-normal text-muted-foreground">자금줄 → 데이터센터 → 전력</span></>}
          info="그룹 안 채권 스프레드의 중앙값입니다. 하이일드는 BB+ 이하 등급입니다.">
          <Table className="text-[13px]">
            <TableHeader><TableRow>
              <TableHead className="h-8 px-1 text-[11px]">그룹</TableHead><TableHead className="h-8 px-1 text-right text-[11px]">중앙값</TableHead>
              <TableHead className="h-8 px-1 text-right text-[11px]">채권</TableHead><TableHead className="h-8 px-1 text-right text-[11px]">하이일드</TableHead>
            </TableRow></TableHeader>
            <TableBody>{creditGroupMedians(rows, data.groups).map(g => <TableRow key={g.key}>
              <TableCell className="whitespace-normal px-1 py-2">{g.label}</TableCell>
              <TableCell className="px-1 py-2 text-right font-mono tabular-nums">{g.median == null ? '-' : `${formatBp(g.median)}bp`}</TableCell>
              <TableCell className="px-1 py-2 text-right font-mono tabular-nums">{g.count}</TableCell>
              <TableCell className="px-1 py-2 text-right font-mono tabular-nums">{g.hy}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </HomeBlock>
      </div></div>
    </div>
  </PageLayout>
}

function SpreadChart({ rows, selected, view, range, onParam, onToggle }: {
  rows: CreditRow[]; selected: string[]; view: 'yield' | 'spread'; range: '3m' | '1y' | 'all'
  onParam: (key: string, value: string | null) => void; onToggle: (t: string) => void
}) {
  const history = useCreditHistory(selected)
  const phone = useIsMobile()
  // 시안 Industry-Credit: 사용자가 고른 회사라 색 구분 — 보라·주의·사실·글자 2 순, 그 뒤는 차트 팔레트
  const extra = useChartPalette(MAX_SELECTED + 1)
  const palette = useMemo(() => ['--hyp', '--warn', '--fact', '--ink-2', ...extra.slice(4, MAX_SELECTED)], [extra])
  const [adding, setAdding] = useState(false)
  const byTicker = useMemo(() => Object.fromEntries(rows.map(r => [r.ticker, r])), [rows])
  const muted = '--ink-3'
  const latest = (key: string) => { const pts = history.data?.points ?? []; for (let i = pts.length - 1; i >= 0; i--) { const v = (pts[i] as Record<string, unknown>)[key]; if (typeof v === 'number') return v } return null }
  const fmt = (v: number | null) => v == null ? '-' : view === 'yield' ? formatYield(v) : `${formatBp(v)}bp`
  // 선 끝 직접 라벨 — 이름(스프레드 보기는 최신 bp까지)
  const lines = useMemo(() => [
    ...(view === 'yield' ? [{ key: 'treasury', label: '미 국채 (같은 만기 평균)', title: '미 국채', color: muted, lineWidth: 2, lineStyle: 2, endLabel: { name: '미 국채', value: fmt(latest('treasury')), dot: true } }] : []),
    ...selected.map((t, i) => { const key = view === 'yield' ? `${t}_ytm` : `${t}_spread`
      return { key, label: byTicker[t]?.name ?? t, title: byTicker[t]?.name ?? t, color: palette[i] ?? '--ink-3', endLabel: { name: byTicker[t]?.name ?? t, value: fmt(latest(key)), dot: true } } }),
  // eslint-disable-next-line react-hooks/exhaustive-deps -- latest·fmt는 history·view에서 나온다
  ], [view, selected, palette, byTicker, history.data])
  const points = useMemo(() => sliceByRange((history.data?.points ?? []) as (Record<string, string | number | null> & { date: string })[], range).map(p => ({ ...p, time: p.date })), [history.data, range])

  return <HomeBlock label="credit.chart" title="스프레드 비교"
    info="회사마다 대표 채권 하나의 만기 수익률과 같은 날 같은 잔존 만기로 보간한 미 국채 금리의 차이(bp)입니다. 차트를 누르면 그날 기준 1일·1주·1개월 변화를 보여 줍니다. 아래 표의 줄을 눌러도 회사를 더하고 뺍니다."
    actions={<div className="flex items-center gap-1.5">
      <ToggleGroup type="single" value={view} onValueChange={v => { if (v) onParam('credit_view', v === 'yield' ? 'yield' : null) }} variant="outline" size="sm" aria-label="차트 보기">
        <ToggleGroupItem value="yield" className="px-2.5 text-xs">수익률</ToggleGroupItem><ToggleGroupItem value="spread" className="px-2.5 text-xs">스프레드</ToggleGroupItem>
      </ToggleGroup>
      <ToggleGroup type="single" value={range} onValueChange={v => { if (v) onParam('credit_range', v === '1y' ? null : v) }} variant="outline" size="sm" aria-label="기간" className="max-sm:hidden">
        <ToggleGroupItem value="3m" className="px-2.5 text-xs">3개월</ToggleGroupItem><ToggleGroupItem value="1y" className="px-2.5 text-xs">1년</ToggleGroupItem><ToggleGroupItem value="all" className="px-2.5 text-xs">전체</ToggleGroupItem>
      </ToggleGroup>
    </div>} bodyClassName="space-y-3">
    <div className="flex flex-wrap items-center gap-2">
      {selected.map((t, i) => <Badge key={t} variant="outline" className="gap-1.5 py-1 pl-2 pr-1 font-normal">
        <span className="size-2 rounded-full" style={{ background: `var(${palette[i]})` }} aria-hidden="true" />{byTicker[t]?.name ?? t}
        <span className="text-muted-foreground">{byTicker[t]?.rating ?? ''}</span>
        <Button variant="ghost" size="icon-xs" className="size-4 text-muted-foreground" aria-label={`${byTicker[t]?.name ?? t} 빼기`} onClick={() => onToggle(t)}><X className="size-3" /></Button>
      </Badge>)}
      <Popover open={adding} onOpenChange={setAdding}><PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 border-dashed text-xs" disabled={selected.length >= MAX_SELECTED}><Plus className="size-3.5" />회사 추가 (최대 {MAX_SELECTED})</Button>
      </PopoverTrigger><PopoverContent align="start" className="w-72 p-0"><Command><CommandInput placeholder="회사 이름·티커" /><CommandList><CommandEmpty>없습니다.</CommandEmpty>
        <CommandGroup>{rows.filter(r => r.spread_bp != null && !selected.includes(r.ticker)).map(r => <CommandItem key={r.ticker} value={`${r.name} ${r.ticker}`} onSelect={() => { onToggle(r.ticker); setAdding(false) }}>
          {r.name}<span className="ml-1 text-caption text-muted-foreground">{r.ticker}</span><span className="ml-auto tabular-nums text-caption text-muted-foreground">{formatBp(r.spread_bp)}bp</span></CommandItem>)}</CommandGroup>
      </CommandList></Command></PopoverContent></Popover>
    </div>
    {!selected.length ? <p role="status" className="py-16 text-center text-sm text-muted-foreground">아래 표에서 회사를 고르면 차트에 더해집니다.</p>
      : history.isPending ? <Skeleton className="h-[340px] w-full" />
      : history.isError ? <ErrorState message="이력을 불러오지 못했습니다." onRetry={() => void history.refetch()} />
      : <MultiLineChart data={points} lines={lines} height={340} showLegend={false} showLastValues={false} endLabels={phone ? undefined : 190} formatValue={v => view === 'yield' ? formatYield(v) : `${formatBp(v)}bp`}
          formatChange={d => `${formatBp(Math.round(view === 'yield' ? d * 100 : d) + 0, true)}bp`} />}
  </HomeBlock>
}

function SpreadTable({ rows, asOf, groups, all, onAll, selected, onToggle }: {
  rows: CreditRow[]; asOf: string | null; groups: { key: string; label: string }[]; all: boolean; onAll: (v: boolean) => void
  selected: string[]; onToggle: (t: string) => void
}) {
  // 체결이 드문 채권은 마지막 값이 며칠 묵는다 — 기준일보다 3일 넘게 오래되면 날짜를 보인다
  const stale = (d: string | null) => !!d && !!asOf && (new Date(asOf).getTime() - new Date(d).getTime()) / 86_400_000 > 3
  const groupLabel = Object.fromEntries(groups.map(g => [g.key, g.label]))
  const sorted = [...rows].sort(bySpread)
  const shown = all ? sorted : sorted.slice(0, TOP)
  return <HomeBlock label="credit.table" title={<>종목별 스프레드 <span className="ml-1 text-xs font-normal text-muted-foreground">넓은 순{all ? '' : ` 상위 ${TOP}`}</span></>}
    info="스프레드 = 대표 채권 만기 수익률 − 같은 날 같은 잔존 만기로 보간한 미 국채 금리(bp). 암시 부도확률은 스프레드에 내재된 5년 누적 확률의 근사(회수율 40% 가정)로, 신용평가가 아닙니다. '유럽 호가'는 미국 체결이 없는 사모채(144A)를 유럽 거래소 호가 수익률로 대신한 것입니다. 1개월 변화는 이력이 쌓이기 전에는 '-'입니다."
    actions={rows.length > TOP ? <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground" onClick={() => onAll(!all)}>{all ? `상위 ${TOP}개만` : `${rows.length}개 모두 ›`}</Button> : null}
    bodyClassName="p-0" bounded="lg">
    <Table className="text-[13px]">
      <TableHeader><TableRow>
        <TableHead className="h-8 pl-3 text-[11px]">기업 · 채권</TableHead><TableHead className="h-8 text-[11px] max-md:hidden">그룹</TableHead>
        <TableHead className="h-8 text-right text-[11px] max-md:hidden">등급</TableHead><TableHead className="h-8 text-right text-[11px] max-sm:hidden">YTM</TableHead>
        <TableHead className="h-8 text-right text-[11px]">스프레드</TableHead><TableHead className="h-8 text-right text-[11px]">1개월</TableHead>
        <TableHead className="h-8 pr-3 text-right text-[11px] max-md:hidden">암시 부도확률</TableHead>
      </TableRow></TableHeader>
      <TableBody>{shown.map(r => {
        const on = selected.includes(r.ticker)
        return <TableRow key={r.ticker} data-credit-row aria-selected={on} className={cn('cursor-pointer', on && 'bg-muted/60')}
          onClick={() => { if (r.spread_bp != null) onToggle(r.ticker) }}>
          <TableCell className="max-w-72 whitespace-normal py-2 pl-3">
            <span className="font-medium">{r.name}</span> <span className="text-caption text-muted-foreground">{r.ticker}</span>
            {r.source === '유럽 거래소' && <span className="ml-1.5 text-[10px] text-muted-foreground">유럽 호가</span>}
            <span className="block truncate text-caption text-muted-foreground" title={r.bond ?? undefined}>{r.bond ?? '-'}</span>
            <span className="text-caption text-muted-foreground md:hidden">{groupLabel[r.group] ?? r.group} · {r.rating ?? '-'}</span>
          </TableCell>
          <TableCell className="min-w-32 max-w-44 whitespace-normal py-2 max-md:hidden">{groupLabel[r.group] ?? r.group}</TableCell>
          <TableCell className="py-2 text-right max-md:hidden">
            <Badge variant="outline" className={cn('px-1.5 font-mono text-[11px]', r.hy ? 'border-chart-warning/50 bg-chart-warning/10 text-chart-warning' : 'text-muted-foreground')}>{r.rating ?? '-'}</Badge>
          </TableCell>
          <TableCell className="py-2 text-right font-mono tabular-nums max-sm:hidden">{formatYield(r.ytm)}{stale(r.last_date) && <span className="block text-[10px] text-warn">{r.last_date?.slice(5)} 체결</span>}</TableCell>
          <TableCell className="py-2 text-right font-mono tabular-nums">{r.spread_bp == null ? '-' : `${formatBp(r.spread_bp)}bp`}</TableCell>
          <TableCell className={cn('py-2 text-right font-mono tabular-nums', tone(r.chg_1m))}>{r.chg_1m == null ? '-' : `${formatBp(r.chg_1m, true)}bp`}</TableCell>
          <TableCell className="py-2 pr-3 text-right font-mono tabular-nums max-md:hidden">{formatRatio(r.pd_pct)}</TableCell>
        </TableRow>
      })}</TableBody>
    </Table>
  </HomeBlock>
}
