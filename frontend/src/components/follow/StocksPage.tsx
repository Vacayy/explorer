import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { type ColumnDef, type SortingState, flexRender, getCoreRowModel, getSortedRowModel, useReactTable } from '@tanstack/react-table'
import { ArrowDown, ArrowLeft, ArrowUp, ArrowUpDown, ChevronDown, LoaderCircle, MoreHorizontal, Play, Plus, SlidersHorizontal, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader, PageLayout } from '@/components/shared/PageLayout'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCompanySearch } from '@/hooks/useCompanySearch'
import { useAddMember, useCreateGroup, useDeleteGroup, useEvaluateGroup, useGroup, useGroupSignals, useGroups, useMigrateWatchlist, usePutRules, useRemoveMember, useStrategyCatalog } from '@/hooks/useGroups'
import { formatKrw, formatNumber, formatPercent, formatRelativeTime } from '@/utils/format'
import type { StockGroupDetail, StockGroupKind, StockGroupMember, StrategyCatalogItem, WatchRule, WatchRuleInput } from '@/types'

const KIND_LABEL: Record<StockGroupKind, string> = { watch: '관심', portfolio: '포트폴리오' }
const changeClass = (value: number | null) => value == null ? 'text-muted-foreground' : value > 0 ? 'text-up' : value < 0 ? 'text-down' : ''
const signedPercent = (value: number | null) => value == null ? '-' : formatPercent(value)
const ruleKey = (rule: WatchRuleInput) => `${rule.strategy_id}:${JSON.stringify(rule.params ?? {})}:${rule.within_days ?? 1}`
const toInput = (rule: WatchRule): WatchRuleInput => ({ strategy_id: rule.strategy_id, params: rule.params, within_days: rule.within_days, source_strategy_id: rule.source_strategy_id, source_version: rule.source_version })
const paramsText = (rule: { params: Record<string, unknown> }) => Object.entries(rule.params ?? {}).map(([key, value]) => `${key} ${String(value)}`).join(' · ')

export default function StocksPage() {
  const [params, setParams] = useSearchParams()
  const groupId = params.get('group') ? Number(params.get('group')) : null
  const open = (id: number | null) => setParams(previous => { const next = new URLSearchParams(previous); if (id == null) next.delete('group'); else next.set('group', String(id)); return next })
  return groupId != null ? <GroupDetail groupId={groupId} onBack={() => open(null)} /> : <GroupList onOpen={open} />
}

function GroupList({ onOpen }: { onOpen: (id: number) => void }) {
  const groups = useGroups()
  const create = useCreateGroup()
  const migrate = useMigrateWatchlist()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [kind, setKind] = useState<StockGroupKind>('watch')
  async function submit() {
    if (!name.trim() || create.isPending) return
    try { const detail = await create.mutateAsync({ name: name.trim(), kind }); setCreating(false); setName(''); onOpen(detail.id) }
    catch (error) { toast.error(error instanceof Error ? error.message : '묶음을 만들지 못했습니다.') }
  }
  const legacy = groups.data?.legacy_watchlist
  return <PageLayout header={<PageHeader title="종목 묶음" description="포트폴리오와 관심 종목을 묶고, 종목별 기술적 조건을 매일 평가해 신호를 봅니다." actions={<Button size="sm" onClick={() => setCreating(true)}><Plus className="size-4" />새 묶음</Button>} />}>
    {groups.isPending && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="묶음 불러오는 중" role="status">{[0, 1, 2].map(i => <Skeleton key={i} className="h-32 w-full" />)}</div>}
    {groups.isError && <ErrorState message="묶음을 불러오지 못했습니다." onRetry={() => groups.refetch()} />}
    {legacy && legacy.count > 0 && !legacy.migrated && <Card className="border-hypothesis/30 bg-hypothesis/5"><CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
      <div><p className="text-sm font-medium">기존 관심종목 {formatNumber(legacy.count)}개가 아직 묶음에 없습니다.</p><p className="text-caption text-muted-foreground">확신도·목표가·논지를 그대로 옮겨 ‘관심 종목’ 묶음을 만듭니다.</p></div>
      <Button size="sm" variant="secondary" disabled={migrate.isPending} onClick={() => migrate.mutateAsync().then(detail => onOpen(detail.id)).catch(error => toast.error(error instanceof Error ? error.message : '이관하지 못했습니다.'))}>{migrate.isPending ? '옮기는 중…' : '묶음으로 옮기기'}</Button>
    </CardContent></Card>}
    {groups.data && (groups.data.items.length === 0 ? <Card><CardContent className="space-y-3 py-10 text-center"><p className="font-medium">아직 묶음이 없습니다.</p><p className="text-sm text-muted-foreground">포트폴리오나 관심 종목 묶음을 만들고 조건을 걸면 매일 장 마감 후 신호를 평가합니다.</p><Button onClick={() => setCreating(true)}><Plus className="size-4" />첫 묶음 만들기</Button></CardContent></Card>
      : <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{groups.data.items.map(group => <Button key={group.id} variant="ghost" className="h-auto flex-col items-stretch gap-2 whitespace-normal rounded-xl border bg-card p-4 text-left" onClick={() => onOpen(group.id)}>
        <span className="flex items-start justify-between gap-2"><span className="font-semibold">{group.name}</span><Badge variant="outline">{KIND_LABEL[group.kind]}</Badge></span>
        <span className="text-caption font-normal text-muted-foreground">{formatNumber(group.member_count)}종목 · 조건 {formatNumber(group.rule_count)}개</span>
        <span className="flex items-center justify-between gap-2 text-sm font-normal"><span className={group.today_signals > 0 ? 'font-medium text-up' : 'text-muted-foreground'}>{group.last_as_of ? `신호 ${formatNumber(group.today_signals)}개` : '아직 평가 전'}</span><span className="text-caption text-muted-foreground">{group.last_as_of ? `${group.last_as_of} 기준` : ''}</span></span>
      </Button>)}</div>)}
    {groups.data?.latest_trade_date && <p className="text-caption text-muted-foreground">평가는 평일 16:40에 자동으로 돌고, 저장된 최신 시세일은 {groups.data.latest_trade_date}입니다. 모델 호출 없이 계산만 하므로 비용이 들지 않습니다.</p>}
    <Dialog open={creating} onOpenChange={setCreating}>
      <DialogContent>
        <DialogHeader><DialogTitle>새 묶음</DialogTitle><DialogDescription>관심 종목은 종목만, 포트폴리오는 수량·매수가도 기록합니다.</DialogDescription></DialogHeader>
        <form className="space-y-3" onSubmit={event => { event.preventDefault(); void submit() }}>
          <div className="space-y-2"><Label htmlFor="group-name">이름</Label><Input id="group-name" value={name} onChange={event => setName(event.target.value)} maxLength={80} autoFocus placeholder="예: 반도체 장비, 내 계좌" /></div>
          <div className="flex gap-2" role="radiogroup" aria-label="묶음 종류">{(['watch', 'portfolio'] as StockGroupKind[]).map(value => <Button key={value} type="button" role="radio" aria-checked={kind === value} variant={kind === value ? 'secondary' : 'outline'} size="sm" onClick={() => setKind(value)}>{KIND_LABEL[value]}</Button>)}</div>
          <DialogFooter><Button type="button" variant="ghost" onClick={() => setCreating(false)}>취소</Button><Button type="submit" disabled={!name.trim() || create.isPending}>{create.isPending ? '만드는 중…' : '만들기'}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </PageLayout>
}

function GroupDetail({ groupId, onBack }: { groupId: number; onBack: () => void }) {
  const group = useGroup(groupId)
  const evaluate = useEvaluateGroup(groupId)
  const remove = useDeleteGroup()
  const [editing, setEditing] = useState<string | null | false>(false) // null = 기본 규칙, string = 종목
  const detail = group.data
  async function runEvaluation() {
    try { const next = await evaluate.mutateAsync(false); toast.success(`${next.last_as_of ?? '오늘'} 기준 평가를 마쳤습니다. 신호 ${formatNumber(next.today_signals)}개`) }
    catch (error) { toast.error(error instanceof Error ? error.message : '평가하지 못했습니다.') }
  }
  async function deleteGroup() {
    if (!detail || !window.confirm(`‘${detail.name}’ 묶음과 조건·평가 이력을 삭제할까요?`)) return
    try { await remove.mutateAsync(groupId); onBack() } catch (error) { toast.error(error instanceof Error ? error.message : '삭제하지 못했습니다.') }
  }
  return <PageLayout header={<PageHeader title={detail?.name ?? '묶음'} description={detail ? `${KIND_LABEL[detail.kind]} · ${formatNumber(detail.members.length)}종목 · 기본 조건 ${formatNumber(detail.rules.default.length)}개${detail.note ? ` · ${detail.note}` : ''}` : ''}
    actions={<div className="flex flex-wrap gap-2"><Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft className="size-4" />묶음 목록</Button>
      {detail && <><Button variant="outline" size="sm" onClick={() => setEditing(null)}><SlidersHorizontal className="size-4" />기본 조건</Button>
        <Button size="sm" disabled={evaluate.isPending} onClick={() => void runEvaluation()}>{evaluate.isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />}지금 평가</Button>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="묶음 더보기"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem variant="destructive" onSelect={() => void deleteGroup()}><Trash2 className="size-4" />묶음 삭제</DropdownMenuItem></DropdownMenuContent></DropdownMenu></>}
    </div>} />}>
    {group.isPending && <div className="space-y-4" role="status" aria-label="묶음 불러오는 중"><Skeleton className="h-10 w-full" /><Skeleton className="h-72 w-full" /></div>}
    {group.isError && <ErrorState message="묶음을 불러오지 못했습니다." onRetry={() => group.refetch()} />}
    {detail && <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-muted-foreground">
        {detail.last_as_of ? <span>{detail.last_as_of} 기준 평가 · 오늘 신호 <span className={detail.today_signals > 0 ? 'font-medium text-up' : ''}>{formatNumber(detail.today_signals)}개</span></span> : <span>아직 평가한 적이 없습니다.</span>}
        {detail.evaluation_pending && detail.latest_trade_date && <span className="text-hypothesis">최신 시세일 {detail.latest_trade_date}은 아직 평가 전입니다. ‘지금 평가’를 누르거나 16:40 자동 실행을 기다리세요.</span>}
        {detail.rules.default.length === 0 && Object.keys(detail.rules.members).length === 0 && <span className="text-hypothesis">조건이 없습니다. ‘기본 조건’에서 전략을 추가하세요.</span>}
      </div>
      <MemberTable detail={detail} onEditRules={code => setEditing(code)} />
      <AddMember detail={detail} />
      <SignalHistory groupId={groupId} />
      <RulesSheet detail={detail} target={editing} onClose={() => setEditing(false)} />
    </>}
  </PageLayout>
}

function MemberTable({ detail, onEditRules }: { detail: StockGroupDetail; onEditRules: (code: string) => void }) {
  const remove = useRemoveMember(detail.id)
  const [sorting, setSorting] = useState<SortingState>([])
  const portfolio = detail.kind === 'portfolio'
  const columns = useMemo<ColumnDef<StockGroupMember>[]>(() => {
    const sortable = (label: string) => ({ column }: { column: { getIsSorted: () => false | 'asc' | 'desc'; getToggleSortingHandler: () => ((event: unknown) => void) | undefined } }) => {
      const sorted = column.getIsSorted(); const Icon = sorted === 'desc' ? ArrowDown : sorted === 'asc' ? ArrowUp : ArrowUpDown
      return <Button variant="ghost" size="sm" className="-mr-2 h-7 gap-1 px-2" onClick={column.getToggleSortingHandler()}>{label}<Icon className="size-3.5" aria-hidden="true" /></Button>
    }
    const list: ColumnDef<StockGroupMember>[] = [
      { id: 'name', accessorKey: 'name', header: '종목', enableSorting: false, cell: ({ row }) => <span className="block"><Link className="font-semibold hover:underline" to={`/analyze/${row.original.stock_code}/summary`}>{row.original.name}</Link><span className="block text-caption text-muted-foreground">{row.original.stock_code}{row.original.conviction ? ` · 확신도 ${row.original.conviction}` : ''}{row.original.target_price ? ` · 목표 ${formatNumber(row.original.target_price)}원` : ''}</span></span> },
      { id: 'close', accessorFn: item => item.close ?? undefined, sortUndefined: 'last', sortDescFirst: true, header: sortable('현재가'), cell: ({ row }) => <span className="block text-right tabular-nums">{row.original.close != null ? `${formatNumber(row.original.close)}원` : '-'}<span className={`block text-caption ${changeClass(row.original.change_pct)}`}>{signedPercent(row.original.change_pct)}</span></span> },
      { id: 'market_cap', accessorFn: item => item.market_cap ?? undefined, sortUndefined: 'last', sortDescFirst: true, header: sortable('시가총액'), cell: ({ row }) => <span className="block text-right tabular-nums">{formatKrw(row.original.market_cap)}</span> },
    ]
    if (portfolio) list.push({ id: 'pnl', accessorFn: item => item.return_pct ?? undefined, sortUndefined: 'last', sortDescFirst: true, header: sortable('평가손익'), cell: ({ row }) => <span className={`block text-right tabular-nums ${changeClass(row.original.return_pct)}`}>{row.original.pnl != null ? formatKrw(row.original.pnl) : '-'}<span className="block text-caption">{signedPercent(row.original.return_pct)}</span></span> })
    list.push(
      { id: 'signals', accessorFn: item => item.signals.length, sortDescFirst: true, header: sortable('오늘 신호'), cell: ({ row }) => row.original.signals.length ? <span className="flex flex-wrap gap-1">{row.original.signals.map(signal => <Badge key={signal.rule_id} className="font-normal">{signal.label}{signal.signal_date && signal.signal_date !== detail.last_as_of ? ` · ${signal.signal_date}` : ''}</Badge>)}</span> : <span className="text-caption text-muted-foreground">{row.original.rule_count === 0 ? '조건 없음' : row.original.unavailable > 0 ? `미평가 ${formatNumber(row.original.unavailable)}` : '-'}</span> },
      { id: 'rules', accessorKey: 'rule_count', header: '조건', enableSorting: false, cell: ({ row }) => <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => onEditRules(row.original.stock_code)} aria-label={`${row.original.name} 조건 편집`}>{formatNumber(row.original.rule_count)}개<SlidersHorizontal className="size-3.5" /></Button> },
      { id: 'actions', header: '', enableSorting: false, cell: ({ row }) => <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${row.original.name} 더보기`}><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
        <DropdownMenuItem asChild><Link to={`/analyze/${row.original.stock_code}/summary`}>기업 개요</Link></DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onEditRules(row.original.stock_code)}>종목 조건 편집</DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onSelect={() => remove.mutateAsync(row.original.stock_code).catch(error => toast.error(error instanceof Error ? error.message : '제거하지 못했습니다.'))}>묶음에서 제거</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu> },
    )
    return list
  }, [detail.id, detail.last_as_of, portfolio, onEditRules, remove])
  const table = useReactTable({ data: detail.members, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getRowId: item => item.stock_code })
  if (detail.members.length === 0) return <Card><CardContent className="py-8 text-center"><p className="font-medium">종목이 없습니다.</p><p className="mt-1 text-sm text-muted-foreground">아래에서 종목을 검색해 넣거나, <Link className="underline" to="/discover">종목 발견</Link> 후보에서 ‘묶음에 추가’를 누르세요.</p></CardContent></Card>
  return <div className="overflow-x-auto rounded-xl bg-card">
    <Table aria-label={`${detail.name} 종목`}>
      <TableHeader>{table.getHeaderGroups().map(group => <TableRow key={group.id}>{group.headers.map(header => <TableHead key={header.id} className={['close', 'market_cap', 'pnl'].includes(header.column.id) ? 'text-right' : undefined}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}</TableRow>)}</TableHeader>
      <TableBody>{table.getRowModel().rows.map(row => <TableRow key={row.id}>{row.getVisibleCells().map(cell => <TableCell key={cell.id} className="align-top whitespace-normal">{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>)}</TableBody>
    </Table>
  </div>
}

function AddMember({ detail }: { detail: StockGroupDetail }) {
  const [query, setQuery] = useState('')
  const [quantity, setQuantity] = useState('')
  const [avgPrice, setAvgPrice] = useState('')
  const search = useCompanySearch(query.trim())
  const add = useAddMember()
  const existing = new Set(detail.members.map(member => member.stock_code))
  async function pick(code: string) {
    try {
      await add.mutateAsync({ groupId: detail.id, stock_code: code, ...(detail.kind === 'portfolio' && quantity ? { quantity: Number(quantity) } : {}), ...(detail.kind === 'portfolio' && avgPrice ? { avg_price: Number(avgPrice) } : {}) })
      setQuery('')
    } catch (error) { toast.error(error instanceof Error ? error.message : '종목을 추가하지 못했습니다.') }
  }
  return <Card><CardHeader className="pb-2"><h2 className="text-sm font-medium">종목 추가</h2></CardHeader><CardContent className="space-y-3">
    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
      <div className="space-y-1"><Label htmlFor="member-search" className="sr-only">종목명 또는 코드</Label><Input id="member-search" value={query} onChange={event => setQuery(event.target.value)} placeholder="종목명 또는 코드" autoComplete="off" /></div>
      {detail.kind === 'portfolio' && <><Input aria-label="수량" type="number" min={0} className="w-28" value={quantity} onChange={event => setQuantity(event.target.value)} placeholder="수량" /><Input aria-label="평균 매수가" type="number" min={0} className="w-36" value={avgPrice} onChange={event => setAvgPrice(event.target.value)} placeholder="평균 매수가" /></>}
    </div>
    {query.trim() && <ul className="max-h-56 space-y-1 overflow-y-auto" aria-label="검색 결과">
      {search.isPending && <li className="text-caption text-muted-foreground">검색 중…</li>}
      {search.data?.slice(0, 8).map(company => <li key={company.stock_code}><Button variant="ghost" size="sm" className="w-full justify-between" disabled={add.isPending || existing.has(company.stock_code)} onClick={() => void pick(company.stock_code)}><span>{company.corp_name}<span className="ml-2 text-caption text-muted-foreground">{company.stock_code}</span></span><span className="text-caption text-muted-foreground">{existing.has(company.stock_code) ? '이미 있음' : '추가'}</span></Button></li>)}
      {search.data && search.data.length === 0 && <li className="text-caption text-muted-foreground">일치하는 종목이 없습니다.</li>}
    </ul>}
  </CardContent></Card>
}

function SignalHistory({ groupId }: { groupId: number }) {
  const signals = useGroupSignals(groupId, 30)
  const byDate = useMemo(() => { const map = new Map<string, NonNullable<typeof signals.data>>(); for (const signal of signals.data ?? []) map.set(signal.as_of, [...(map.get(signal.as_of) ?? []), signal]); return [...map.entries()] }, [signals.data])
  return <Collapsible defaultOpen className="rounded-xl bg-card px-4 py-2">
    <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="h-auto w-full justify-between whitespace-normal text-left">최근 30일 신호 {signals.data ? `· ${formatNumber(signals.data.length)}건` : ''}<ChevronDown className="size-4 shrink-0" /></Button></CollapsibleTrigger>
    <CollapsibleContent className="space-y-3 pb-3 pt-2">
      {signals.isPending && <Skeleton className="h-16 w-full" />}
      {signals.isError && <ErrorState message="신호 이력을 불러오지 못했습니다." onRetry={() => signals.refetch()} />}
      {signals.data && signals.data.length === 0 && <EmptyState message="최근 30일 동안 새로 켜진 신호가 없습니다. 조건이 켜진 첫날만 기록합니다." />}
      {byDate.map(([date, items]) => <div key={date} className="space-y-1"><p className="text-caption font-medium text-muted-foreground">{date}</p><ul className="space-y-1">{items.map(signal => <li key={`${signal.stock_code}-${signal.rule_id}`} className="flex flex-wrap items-baseline gap-x-2 text-sm"><Link className="font-medium hover:underline" to={`/analyze/${signal.stock_code}/summary`}>{signal.name ?? signal.stock_code}</Link><span>{signal.label}</span>{signal.value != null && <span className="text-caption tabular-nums text-muted-foreground">{formatNumber(signal.value)}{signal.reference != null ? ` / ${formatNumber(signal.reference)}` : ''}</span>}</li>)}</ul></div>)}
    </CollapsibleContent>
  </Collapsible>
}

function RulesSheet({ detail, target, onClose }: { detail: StockGroupDetail; target: string | null | false; onClose: () => void }) {
  const open = target !== false
  const code = target === false ? null : target
  const member = code ? detail.members.find(item => item.stock_code === code) : null
  return <Sheet open={open} onOpenChange={value => { if (!value) onClose() }}>
    <SheetContent className="w-full overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
      <SheetHeader><SheetTitle>{code ? `${member?.name ?? code} 조건` : '묶음 기본 조건'}</SheetTitle><SheetDescription>{code ? '이 종목에만 추가되는 조건입니다. 기본 조건과 같은 전략이면 이 값이 우선합니다.' : '묶음의 모든 종목에 적용됩니다. 매일 장 마감 후 계산합니다.'}</SheetDescription></SheetHeader>
      {open && <div className="px-4 pb-6 sm:px-6"><RuleEditor key={`${detail.id}:${code ?? 'default'}`} detail={detail} code={code} onSaved={onClose} /></div>}
    </SheetContent>
  </Sheet>
}

function RuleEditor({ detail, code, onSaved }: { detail: StockGroupDetail; code: string | null; onSaved: () => void }) {
  const catalog = useStrategyCatalog()
  const put = usePutRules(detail.id)
  const initial = (code ? detail.rules.members[code] ?? [] : detail.rules.default).map(toInput)
  const [rules, setRules] = useState<WatchRuleInput[]>(initial)
  const [strategyId, setStrategyId] = useState('')
  const [params, setParams] = useState<Record<string, unknown>>({})
  const [within, setWithin] = useState('1')
  const usable = useMemo(() => (catalog.data ?? []).filter(item => !item.id.startsWith('rank_') && item.timeframe !== '10m'), [catalog.data])
  const selected = usable.find(item => item.id === strategyId)
  const inherited = code ? detail.rules.default.filter(rule => !rules.some(item => item.strategy_id === rule.strategy_id)) : []
  const dirty = JSON.stringify(rules.map(ruleKey)) !== JSON.stringify(initial.map(ruleKey))
  function choose(id: string) { const item = usable.find(entry => entry.id === id); setStrategyId(id); setParams({ ...(item?.defaults ?? {}) }) }
  function addRule() {
    if (!selected) return
    const next: WatchRuleInput = { strategy_id: selected.id, params, within_days: Math.max(1, Math.min(250, Number(within) || 1)) }
    if (rules.some(rule => ruleKey(rule) === ruleKey(next))) { toast.message('같은 조건이 이미 있습니다.'); return }
    setRules([...rules, next]); setStrategyId(''); setParams({}); setWithin('1')
  }
  async function save() {
    const members = Object.fromEntries(Object.entries(detail.rules.members).map(([key, list]) => [key, list.map(toInput)]))
    const body = code ? { default: detail.rules.default.map(toInput), members: { ...members, [code]: rules } } : { default: rules, members }
    if (code && rules.length === 0) delete body.members[code]
    try { await put.mutateAsync(body); toast.success('조건을 저장했습니다. 다음 평가부터 적용됩니다.'); onSaved() }
    catch (error) { toast.error(error instanceof Error ? error.message : '조건을 저장하지 못했습니다.') }
  }
  const labelOf = (id: string) => catalog.data?.find(item => item.id === id)?.label ?? id
  return <div className="space-y-5 pt-4">
    <section className="space-y-2" aria-label="현재 조건">
      {rules.length === 0 && <p className="text-sm text-muted-foreground">{code ? '이 종목에만 붙은 조건이 없습니다.' : '조건이 없습니다. 아래에서 전략을 골라 추가하세요.'}</p>}
      {rules.map((rule, index) => <div key={ruleKey(rule)} className="flex items-start justify-between gap-2 rounded-lg border p-3"><div className="min-w-0"><p className="text-sm font-medium">{labelOf(rule.strategy_id)}</p><p className="text-caption text-muted-foreground">{paramsText({ params: rule.params ?? {} }) || '기본 매개변수'} · 최근 {rule.within_days ?? 1}거래일{rule.source_strategy_id ? ' · 저장 전략에서 복사' : ''}</p></div><Button variant="ghost" size="icon-sm" aria-label={`${labelOf(rule.strategy_id)} 조건 제거`} onClick={() => setRules(rules.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button></div>)}
      {inherited.length > 0 && <div className="space-y-1 rounded-lg bg-muted/50 p-3"><p className="text-caption font-medium text-muted-foreground">기본 조건에서 이어받음</p>{inherited.map(rule => <p key={rule.id} className="text-caption text-muted-foreground">{rule.label} · {paramsText(rule) || '기본 매개변수'}</p>)}</div>}
    </section>
    <section className="space-y-3 rounded-lg border p-3" aria-label="조건 추가">
      <p className="text-sm font-medium">조건 추가</p>
      {catalog.isPending && <Skeleton className="h-9 w-full" />}
      {catalog.isError && <ErrorState message="전략 목록을 불러오지 못했습니다." onRetry={() => catalog.refetch()} />}
      {catalog.data && <>
        <Select value={strategyId} onValueChange={choose}><SelectTrigger aria-label="전략 선택"><SelectValue placeholder="전략을 선택하세요" /></SelectTrigger><SelectContent className="max-h-80">{usable.map(item => <SelectItem key={item.id} value={item.id}>{item.category} · {item.label}</SelectItem>)}</SelectContent></Select>
        {selected && <ParamFields item={selected} values={params} onChange={setParams} />}
        {selected && <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-2"><div className="space-y-1"><Label htmlFor="rule-within">최근 N거래일 안에 발생</Label><Input id="rule-within" type="number" min={1} max={250} value={within} onChange={event => setWithin(event.target.value)} /></div><Button type="button" variant="secondary" onClick={addRule}><Plus className="size-4" />추가</Button></div>}
        {selected?.description && <p className="text-caption text-muted-foreground">{selected.description}</p>}
      </>}
    </section>
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-caption text-muted-foreground">{dirty ? '저장하지 않은 변경이 있습니다.' : '변경 없음'}</p><Button disabled={!dirty || put.isPending} onClick={() => void save()}>{put.isPending ? '저장 중…' : '조건 저장'}</Button></div>
  </div>
}

function ParamFields({ item, values, onChange }: { item: StrategyCatalogItem; values: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void }) {
  const entries = Object.entries(item.parameters ?? {})
  if (entries.length === 0) return <p className="text-caption text-muted-foreground">매개변수가 없는 전략입니다.</p>
  return <div className="grid gap-3 sm:grid-cols-2">{entries.map(([key, schema]) => <div key={key} className="space-y-1">
    <Label htmlFor={`param-${key}`}>{schema.label ?? key}</Label>
    {schema.type === 'string' ? <Select value={String(values[key] ?? '')} onValueChange={value => onChange({ ...values, [key]: value })}><SelectTrigger id={`param-${key}`}><SelectValue /></SelectTrigger><SelectContent>{(schema.options ?? []).map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select>
      : <Input id={`param-${key}`} type="number" min={schema.min} max={schema.max} step={schema.type === 'integer' ? 1 : 'any'} value={values[key] == null ? '' : String(values[key])} onChange={event => { const raw = event.target.value; onChange({ ...values, [key]: raw === '' ? undefined : schema.type === 'integer' ? Math.trunc(Number(raw)) : Number(raw) }) }} />}
    {(schema.min != null || schema.max != null) && <p className="text-caption text-muted-foreground">{schema.min ?? ''}{schema.min != null && schema.max != null ? ' ~ ' : ''}{schema.max ?? ''}</p>}
  </div>)}</div>
}
