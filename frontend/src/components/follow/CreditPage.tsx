import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Plus, X } from 'lucide-react'
import { PageContainer } from '@/components/shared/PageContainer'
import { ErrorState } from '@/components/shared/ErrorState'
import MultiLineChart from '@/components/charts/MultiLineChart'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useCreditHistory, useCreditTable } from '@/hooks/useCredit'
import { useChartPalette } from '@/hooks/useChartPalette'
import { formatBp, formatRatio, formatYield } from '@/utils/format'
import type { CreditRow } from '@/types'

const MAX_SELECTED = 6
const DEFAULT_SELECTED = ['ORCL', 'META']
const tone = (v: number | null) => v == null || v === 0 ? 'text-muted-foreground' : v > 0 ? 'text-up' : 'text-down'   // 스프레드 확대 = 빨강
/** "Oracle Corporation 4.8% 26-SEP-2032" → "4.8% 2032" */
const shortBond = (bond: string | null) => bond?.match(/(\d+(?:\.\d+)?%)\s+\d{2}-[A-Z]{3}-(\d{4})/)?.slice(1).join(' ') ?? bond ?? '-'

/**
 * 회사채 스프레드(D-230, docs/specs/credit-spreads.md) — 회사마다 대표 채권 하나의 수익률과 같은 만기 국채의 차이.
 * 선택 회사는 URL `credit`, 차트 모드는 `credit_view`, 묶음 필터는 `credit_group`.
 */
export default function CreditPage() {
  const [params, setParams] = useSearchParams()
  const table = useCreditTable()
  const selected = (params.get('credit')?.split(',').filter(Boolean) ?? DEFAULT_SELECTED).slice(0, MAX_SELECTED)
  const view = params.get('credit_view') === 'spread' ? 'spread' : 'yield'
  const group = params.get('credit_group') ?? 'all'
  const set = (key: string, value: string | null) => setParams(prev => { const n = new URLSearchParams(prev); if (value) n.set(key, value); else n.delete(key); return n }, { replace: true })
  const toggle = (ticker: string) => set('credit', (selected.includes(ticker) ? selected.filter(t => t !== ticker) : [...selected, ticker].slice(-MAX_SELECTED)).join(',') || '-')

  if (table.isPending) return <PageContainer><Skeleton className="h-80 w-full rounded-xl" /><Skeleton className="h-96 w-full rounded-xl" /></PageContainer>
  if (table.isError) return <PageContainer><ErrorState message="회사채 스프레드를 불러오지 못했습니다." onRetry={() => void table.refetch()} /></PageContainer>
  const data = table.data
  const rows = data.rows
  const collected = rows.some(r => r.spread_bp != null)

  return <PageContainer>
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-xl font-bold">회사채 스프레드</h2>
      <span className="text-caption text-muted-foreground">회사당 대표 채권 1개 · 일별 종가 수익률 − 같은 만기 미 국채{data.as_of ? ` · ${data.as_of} 기준` : ''}</span>
    </div>
    {!data.configured ? <Card><CardContent className="space-y-2 py-10 text-center">
        <p className="font-medium">채권 데이터 원천이 설정되지 않았습니다</p>
        <p className="text-sm text-muted-foreground">이 기능은 로컬 데이터 원천 어댑터(backend/local_sources/credit_source.py, 공개 저장소 밖)가 있어야 수집합니다. 국채 곡선과 계산은 준비돼 있습니다.</p>
      </CardContent></Card>
      : !collected ? <Card><CardContent className="space-y-2 py-10 text-center">
        <p className="font-medium">아직 수집된 채권이 없습니다</p>
        <p className="text-sm text-muted-foreground">매일 07:30에 수집합니다. 지금 받으려면 scripts/collect_credit.py를 실행하세요.</p>
      </CardContent></Card>
      : <>
        <SpreadChart rows={rows} selected={selected} view={view} onView={v => set('credit_view', v === 'spread' ? 'spread' : null)} onToggle={toggle} />
        <SpreadTable rows={rows} asOf={data.as_of} groups={data.groups} group={group} onGroup={g => set('credit_group', g === 'all' ? null : g)} selected={selected} onToggle={toggle} />
      </>}
  </PageContainer>
}

function SpreadChart({ rows, selected, view, onView, onToggle }: {
  rows: CreditRow[]; selected: string[]; view: 'yield' | 'spread'; onView: (v: string) => void; onToggle: (t: string) => void
}) {
  const history = useCreditHistory(selected)
  const palette = useChartPalette(MAX_SELECTED + 1)
  const [adding, setAdding] = useState(false)
  const byTicker = Object.fromEntries(rows.map(r => [r.ticker, r]))
  const muted = palette[MAX_SELECTED] ? getComputedStyle(document.documentElement).getPropertyValue('--muted-foreground').trim() || '#888' : '#888'
  const lines = useMemo(() => [
    ...(view === 'yield' ? [{ key: 'treasury', label: '미 국채 (같은 만기 평균)', color: muted, lineWidth: 2 }] : []),
    ...selected.map((t, i) => ({ key: view === 'yield' ? `${t}_ytm` : `${t}_spread`, label: byTicker[t]?.name ?? t, color: palette[i] ?? '#888' })),
  ], [view, selected, palette, muted, byTicker])
  const points = useMemo(() => (history.data?.points ?? []).map(p => ({ ...p, time: p.date })), [history.data])

  return <Card>
    <CardContent className="space-y-4 pt-5">
      <div className="flex flex-wrap items-center gap-2">
        {selected.map((t, i) => <Badge key={t} variant="outline" className="gap-1.5 py-1 pl-2 pr-1 font-normal">
          <span className="size-2 rounded-full" style={{ background: palette[i] }} aria-hidden="true" />{byTicker[t]?.name ?? t}
          <span className="tabular-nums text-muted-foreground">{formatBp(byTicker[t]?.spread_bp)}bp</span>
          <button type="button" className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground" aria-label={`${byTicker[t]?.name ?? t} 빼기`} onClick={() => onToggle(t)}><X className="size-3" /></button>
        </Badge>)}
        <Popover open={adding} onOpenChange={setAdding}><PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="h-7 border-dashed" disabled={selected.length >= MAX_SELECTED}><Plus className="size-3.5" />회사 추가</Button>
        </PopoverTrigger><PopoverContent align="start" className="w-72 p-0"><Command><CommandInput placeholder="회사 이름·티커" /><CommandList><CommandEmpty>없습니다.</CommandEmpty>
          <CommandGroup>{rows.filter(r => r.spread_bp != null && !selected.includes(r.ticker)).map(r => <CommandItem key={r.ticker} value={`${r.name} ${r.ticker}`} onSelect={() => { onToggle(r.ticker); setAdding(false) }}>
            {r.name}<span className="ml-1 text-caption text-muted-foreground">{r.ticker}</span><span className="ml-auto tabular-nums text-caption text-muted-foreground">{formatBp(r.spread_bp)}bp</span></CommandItem>)}</CommandGroup>
        </CommandList></Command></PopoverContent></Popover>
      </div>
      <ToggleGroup type="single" value={view} onValueChange={v => { if (v) onView(v) }} variant="outline" size="sm" className="justify-start" aria-label="차트 보기">
        <ToggleGroupItem value="yield" className="px-3">수익률 + 국채</ToggleGroupItem><ToggleGroupItem value="spread" className="px-3">스프레드</ToggleGroupItem>
      </ToggleGroup>
      {!selected.length ? <p className="py-16 text-center text-sm text-muted-foreground">아래 표에서 회사를 골라 차트에 더하세요.</p>
        : history.isPending ? <Skeleton className="h-[360px] w-full" />
        : history.isError ? <ErrorState message="이력을 불러오지 못했습니다." onRetry={() => void history.refetch()} />
        : <>
          <MultiLineChart data={points} lines={lines} height={360} formatValue={v => view === 'yield' ? formatYield(v) : `${formatBp(v)}bp`}
            formatChange={d => `${formatBp(Math.round(view === 'yield' ? d * 100 : d) + 0, true)}bp`} />
          <p className="text-caption text-muted-foreground">차트를 누르면 그날 기준 1일·1주·1개월 변화를 보여줍니다.</p>
        </>}
    </CardContent>
  </Card>
}

function SpreadTable({ rows, asOf, groups, group, onGroup, selected, onToggle }: {
  rows: CreditRow[]; asOf: string | null; groups: { key: string; label: string }[]; group: string; onGroup: (g: string) => void; selected: string[]; onToggle: (t: string) => void
}) {
  // 체결이 드문 채권은 마지막 값이 며칠 묵는다 — 기준일보다 3일 넘게 오래되면 날짜를 보인다
  const stale = (d: string | null) => !!d && !!asOf && (new Date(asOf).getTime() - new Date(d).getTime()) / 86_400_000 > 3
  const max = Math.max(1, ...rows.map(r => r.spread_bp ?? 0))
  const shown = groups.filter(g => group === 'all' || g.key === group)
  return <Card>
    <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
      <CardTitle>회사별 스프레드</CardTitle>
      <ToggleGroup type="single" value={group} onValueChange={v => { if (v) onGroup(v) }} variant="outline" size="sm" className="flex-wrap justify-start" aria-label="묶음">
        <ToggleGroupItem value="all" className="px-3">전체</ToggleGroupItem>
        {groups.map(g => <ToggleGroupItem key={g.key} value={g.key} className="px-3">{g.label}</ToggleGroupItem>)}
      </ToggleGroup>
    </CardHeader>
    <CardContent className="overflow-x-auto">
      <Table>
        <TableHeader><TableRow>
          <TableHead className="w-10" /><TableHead>회사</TableHead><TableHead>대표 채권</TableHead><TableHead className="text-right">등급</TableHead>
          <TableHead className="text-right">수익률</TableHead><TableHead className="text-right">국채</TableHead><TableHead className="text-right">스프레드</TableHead>
          <TableHead className="text-right">1개월</TableHead><TableHead className="text-right">3개월</TableHead><TableHead className="text-right">1년</TableHead><TableHead className="text-right">부도확률</TableHead>
        </TableRow></TableHeader>
        <TableBody>{shown.map(g => {
          const items = rows.filter(r => r.group === g.key).sort((a, b) => (b.spread_bp ?? -1) - (a.spread_bp ?? -1))
          return [<TableRow key={`h-${g.key}`} className="hover:bg-transparent"><TableCell colSpan={11} className="pb-1 pt-4 text-caption text-muted-foreground">{g.label}</TableCell></TableRow>,
            ...items.map(r => {
              const on = selected.includes(r.ticker)
              return <TableRow key={r.ticker} className={on ? 'bg-primary/5' : ''}>
                <TableCell><Button variant={on ? 'default' : 'outline'} size="icon-sm" className="size-7 rounded-full" disabled={r.spread_bp == null}
                  aria-label={on ? `${r.name} 차트에서 빼기` : `${r.name} 차트에 더하기`} onClick={() => onToggle(r.ticker)}>{on ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}</Button></TableCell>
                <TableCell className="whitespace-nowrap"><span className="font-medium">{r.name}</span> <span className="text-caption text-muted-foreground">{r.ticker}</span>
                  {r.hy && <Badge variant="outline" className="ml-1.5 border-up/40 px-1 text-[10px] text-up">HY</Badge>}
                  {r.source === '유럽 거래소' && <span className="ml-1.5 text-[10px] text-muted-foreground" title="미국 체결이 아니라 유럽 거래소 호가에서 나온 수익률">유럽 호가</span>}</TableCell>
                <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground" title={r.bond ?? undefined}>{shortBond(r.bond)}</TableCell>
                <TableCell className="text-right">{r.rating ?? '-'}</TableCell>
                <TableCell className="text-right tabular-nums">{formatYield(r.ytm)}{stale(r.last_date) && <span className="block text-[10px] text-hypothesis" title="마지막 체결일">{r.last_date?.slice(5)} 체결</span>}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{formatYield(r.treasury)}</TableCell>
                <TableCell className="text-right"><span className="inline-flex items-center justify-end gap-2">
                  <span className="font-semibold tabular-nums">{formatBp(r.spread_bp)}</span>
                  <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted" aria-hidden="true"><span className="block h-full rounded-full bg-up/70" style={{ width: `${Math.max(0, (r.spread_bp ?? 0) / max * 100)}%` }} /></span>
                </span></TableCell>
                {[r.chg_1m, r.chg_3m, r.chg_1y].map((v, i) => <TableCell key={i} className={`text-right tabular-nums ${tone(v)}`}>{v == null ? '—' : formatBp(v, true)}</TableCell>)}
                <TableCell className="text-right tabular-nums">{formatRatio(r.pd_pct)}</TableCell>
              </TableRow>
            })]
        })}</TableBody>
      </Table>
      <p className="mt-3 text-caption text-muted-foreground">스프레드 = 대표 채권 만기 수익률 − 같은 날 같은 잔존 만기로 보간한 미 국채 금리(bp). 부도확률은 스프레드에 내재된 5년 누적 확률의 근사(회수율 40% 가정)로, 신용평가가 아닙니다. ‘유럽 호가’는 미국 체결이 없는 사모채(144A)를 유럽 거래소 호가 수익률로 대신한 것입니다.</p>
    </CardContent>
  </Card>
}
