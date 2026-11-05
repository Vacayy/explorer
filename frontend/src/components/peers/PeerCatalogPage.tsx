import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import { PageContainer } from '@/components/shared/PageContainer'
import PeriodToggle from '@/components/shared/PeriodToggle'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { PeerPerformanceBody, PeerResearchBody, PeerIndustriesBody, PeerIndustriesResearch } from '@/components/peers/PeerBodies'
import { usePeerRuntime } from '@/hooks/usePeerRuntime'
import { useSectorPeers } from '@/hooks/useSectorMap'
import { companyEvidence, groupForStocks, peerDays, peerFinder, peerGroupParam, peerGroupSummary, peerIndustryOf, peerMemberRows, peerView, selectPeerGroup, switchPeerView, type PeerListItem } from '@/lib/peerFrame'
import { sectorOfPeerGroup } from '@/lib/sectorPeers'
import { cn } from '@/lib/utils'
import { formatPercent, formatPp } from '@/utils/format'
import type { PeerCatalog, PeerRuntime } from '@/types/peer'

const tone = (value: number | null | undefined) => value == null ? 'text-muted-foreground' : value > 0 ? 'text-up' : value < 0 ? 'text-down' : ''
const shortDate = (iso: string | null) => iso ? iso.slice(5).replace('-', '/') : '-'

/**
 * /discover/peers — 탐색 › Peer 그룹 (ia-redesign §4.12, docs/specs/peer-groups.md).
 * 머리(경로·보기 전환) · 요약 띠 · 왼쪽 그룹 찾기 · 선택한 종목 띠는 두 보기가 같이 쓰고 본문만 바뀐다. URL = view·group·stock·days·q.
 */
export default function PeerCatalogPage() {
  const runtime = usePeerRuntime()
  return <PageContainer>
    {runtime.isPending ? <PeerLoading />
      : runtime.isError || !runtime.data ? <><PeerHead catalog={null} groupId="" /><ErrorState error={runtime.error} onRetry={() => runtime.refetch()} /></>
      : <PeerFrame data={runtime.data} />}
  </PageContainer>
}

function PeerLoading() {
  return <div aria-label="Peer 그룹 불러오는 중" role="status" className="space-y-3">
    <Skeleton className="h-9 w-40" /><Skeleton className="h-4 w-72" />
    <div className="grid grid-cols-2 border md:grid-cols-4">{[0, 1, 2, 3].map(i => <div key={i} className="space-y-2 p-4"><Skeleton className="h-3 w-16" /><Skeleton className="h-6 w-24" /></div>)}</div>
    <div className="grid gap-4 md:grid-cols-[280px_minmax(0,1fr)]"><Skeleton className="hidden h-[520px] md:block" /><div className="h-[520px]" /></div>
  </div>
}

function PeerFrame({ data }: { data: PeerRuntime }) {
  const { catalog, prices } = data
  const [params, setParams] = useSearchParams()
  const [sheetOpen, setSheetOpen] = useState(false)
  const view = peerView(params)
  const days = peerDays(params)
  const groupId = peerGroupParam(params)
  const query = params.get('q') ?? ''
  const group = catalog.groups.find(item => item.id === groupId)
  const unknown = !!groupId && !group
  const rows = useMemo(() => group ? peerMemberRows(catalog, prices, group.id, days) : [], [catalog, prices, group, days])
  const summary = useMemo(() => group ? peerGroupSummary(catalog, prices, group.id) : null, [catalog, prices, group])
  const requested = params.get('stock')
  const selected = requested ? rows.find(row => row.code === requested) ?? null : rows.find(row => row.rank !== null) ?? rows[0] ?? null
  const missingStock = !!requested && !!group && !selected
  const finder = useMemo(() => peerFinder(catalog, prices, group ? group.id : '', query), [catalog, prices, group, query])
  // /analyze/compare?stocks=A,B 에서 넘어오면 그 종목들이 가장 많이 든 그룹과 첫 종목을 연다(못 찾으면 업종 전체)
  const stocks = params.get('stocks')
  useEffect(() => {
    if (!stocks) return
    const codes = stocks.split(',')
    const target = params.get('group') ? null : groupForStocks(catalog, codes)
    setParams(previous => {
      const next = target ? selectPeerGroup(previous, target) : new URLSearchParams(previous)
      next.delete('stocks')
      const first = target && codes.find(code => catalog.companies.some(c => c.code === code && c.groupIds.includes(target)))
      if (first) next.set('stock', first)
      return next
    }, { replace: true })
  }, [stocks, catalog, params, setParams])
  const pick = (id: string) => { setSheetOpen(false); setParams(previous => selectPeerGroup(previous, id)) }
  const setQuery = (value: string) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set('q', value); else next.delete('q'); return next }, { replace: true })
  const setView = (next: string, stock?: string) => setParams(previous => switchPeerView(previous, next === 'research' ? 'research' : 'performance', stock))
  const selectStock = (code: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set('stock', code); return next }, { replace: true, preventScrollReset: true })
  const setDays = (value: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set('days', value); return next }, { replace: true, preventScrollReset: true })

  const finderList = <PeerFinder finder={finder} groupId={group?.id ?? ''} query={query} onQuery={setQuery} onPick={pick} />
  const stale = data.lastAttempt?.status === 'error' || data.snapshotAgeHours > 72
  return <>
    <PeerHead catalog={catalog} groupId={group?.id ?? ''} view={view} onView={value => setView(value)} onPick={pick} onOpenFinder={() => setSheetOpen(true)} memberCount={rows.length} />
    <div className="sticky top-(--topbar-height) z-20 -mx-1 bg-background px-1 py-1 md:hidden [&>div]:flex [&>div]:w-full [&_button]:flex-1"><ViewToggle view={view} onView={value => setView(value)} /></div>
    <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
      <SheetContent side="bottom" className="max-h-[85dvh] overflow-y-auto"><SheetHeader><SheetTitle>그룹 바꾸기</SheetTitle><SheetDescription className="sr-only">업종과 사업군을 고릅니다</SheetDescription></SheetHeader><div className="px-4 pb-6">{finderList}</div></SheetContent>
    </Sheet>
    {stale && <p role="status" className="text-caption text-chart-warning">{data.lastAttempt?.status === 'error' ? `마지막 수집에 실패해 ${prices.asOf} 가격으로 보여 드립니다.` : `가격이 ${prices.asOf} 이후 갱신되지 않았습니다.`}</p>}
    {group && summary && <SummaryStrip summary={summary} />}
    <div className="grid min-w-0 gap-4 md:grid-cols-[280px_minmax(0,1fr)]">
      <aside aria-label="그룹 찾기" className="hidden min-w-0 self-start border md:block md:sticky md:top-[calc(var(--topbar-height)+1rem)] md:max-h-[calc(100dvh-var(--topbar-height)-2rem)] md:overflow-y-auto">{finderList}</aside>
      <div className="min-w-0 space-y-4">
        {unknown ? <div role="status" className="space-y-2 border p-6">
          <p className="text-sm">이 업종에는 아직 Peer 그룹이 없습니다.</p>
          <Button variant="link" className="h-auto p-0" onClick={() => pick('')}>업종 전체로 돌아가기 ›</Button>
        </div>
          : !group ? (view === 'research' ? <PeerIndustriesResearch catalog={catalog} onPick={pick} /> : <PeerIndustriesBody catalog={catalog} snapshot={prices} days={days} onDays={setDays} onPick={pick} />)
          : <>
            {missingStock ? <p role="status" className="border bg-muted/40 p-3 text-sm">선택한 종목이 이 그룹에 없습니다. 목록에서 종목을 다시 골라 주세요.</p>
              : selected && <SelectedBand view={view} row={selected} catalog={catalog} rows={rows} days={days} onOther={() => setView(view === 'research' ? 'performance' : 'research', selected.code)} />}
            {view === 'research'
              ? <PeerResearchBody catalog={catalog} group={group} rows={rows} days={days} selected={selected?.code ?? null} onSelect={selectStock} onPick={pick} onPerformance={code => setView('performance', code)} />
              : <PeerPerformanceBody data={data} group={group} rows={rows} days={days} onDays={setDays} selected={selected?.code ?? null} onSelect={selectStock} onResearch={code => setView('research', code)} onPick={pick} />}
          </>}
      </div>
    </div>
  </>
}

/** 머리 — 제목·경로(누르면 그 단계로) · 보기 전환 · 업황 링크. 모바일은 경로 카드 + '바꾸기' 시트 */
function PeerHead({ catalog, groupId, view = 'performance', onView, onPick, onOpenFinder, memberCount = 0 }: {
  catalog: PeerCatalog | null; groupId: string; view?: string; onView?: (value: string) => void; onPick?: (id: string) => void; onOpenFinder?: () => void; memberCount?: number
}) {
  const group = catalog?.groups.find(item => item.id === groupId)
  const industryId = catalog && group ? peerIndustryOf(catalog, group.id) : null
  const industry = industryId && industryId !== groupId ? catalog?.groups.find(item => item.id === industryId) : undefined
  const sectorPeers = useSectorPeers()
  const sector = catalog && group && sectorPeers.data ? sectorOfPeerGroup(catalog, sectorPeers.data.sectors, group.id) : null
  const crumbs: { id: string; name: string }[] = [{ id: '', name: '업종 전체' }, ...(industry ? [industry] : []), ...(group ? [group] : [])]
  return <header className="space-y-3">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0 max-md:hidden">
        <h1 className="text-page font-semibold">Peer 그룹</h1>
        <nav aria-label="그룹 경로" className="mt-1 flex flex-wrap items-center gap-1 text-caption text-muted-foreground">
          {crumbs.map((crumb, index) => <span key={crumb.id || 'all'} className="flex items-center gap-1">
            {index > 0 && <ChevronRight className="size-3" aria-hidden="true" />}
            {index === crumbs.length - 1 ? <span aria-current="page" className="font-semibold text-foreground">{crumb.name}</span>
              : <button type="button" className="hover:text-foreground hover:underline" onClick={() => onPick?.(crumb.id)}>{crumb.name}</button>}
          </span>)}
        </nav>
      </div>
      {catalog && <div className="flex flex-wrap items-center gap-3">
        <div className="max-md:hidden"><ViewToggle view={view} onView={onView} /></div>
        {sector && <Link to={`/map?group=${encodeURIComponent(sector)}`} className="text-sm font-semibold hover:underline max-md:hidden">이 그룹의 업황 보기 ›</Link>}
      </div>}
    </div>
    {catalog && <div className="flex items-center justify-between gap-3 border p-3 md:hidden">
      <div className="min-w-0">
        <p className="truncate text-caption text-muted-foreground">{crumbs.slice(0, -1).map(crumb => crumb.name).join(' › ') || 'Peer 그룹'}</p>
        <p className="truncate font-semibold">{group?.name ?? '업종 전체'}{group && <span className="ml-1 text-caption font-normal text-muted-foreground">{memberCount}사</span>}</p>
      </div>
      <Button variant="ghost" size="sm" onClick={onOpenFinder}>바꾸기<ChevronDown className="size-3.5" /></Button>
    </div>}
  </header>
}

function ViewToggle({ view, onView }: { view: string; onView?: (value: string) => void }) {
  return <PeriodToggle value={view} onChange={value => onView?.(value)} options={[{ value: 'performance', label: '성과 비교' }, { value: 'research', label: '사업 근거' }]} />
}

function Cell({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return <div className="min-w-0 p-3 md:p-4"><p className="text-caption text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums md:text-2xl">{children}</p>{sub && <p className="mt-1 text-caption text-muted-foreground">{sub}</p>}</div>
}

function SummaryStrip({ summary }: { summary: NonNullable<ReturnType<typeof peerGroupSummary>> }) {
  const partial = summary.covered < summary.memberCount
  return <section aria-label="그룹 요약" className="grid grid-cols-2 divide-x divide-y border md:grid-cols-4 md:divide-y-0 [&>*:nth-child(2)]:max-md:border-r-0">
    <div className="max-md:order-3"><Cell label="구성" sub={<>{summary.scope === 'product' ? '제품·공정 그룹' : '밸류체인'}{summary.parent && <span className="max-md:hidden"> · 상위 업종 {summary.parent.name}</span>}</>}>{summary.memberCount}사</Cell></div>
    <div className="max-md:order-1"><Cell label={`그룹 평균 · 60일${partial ? ` · ${summary.covered}/${summary.memberCount}사` : ''}`} sub={<>20일 <span className={tone(summary.avg[20])}>{formatPercent(summary.avg[20])}</span> · 5일 <span className={tone(summary.avg[5])}>{formatPercent(summary.avg[5])}</span></>}><span className={tone(summary.avg[60])}>{formatPercent(summary.avg[60])}</span></Cell></div>
    <div className="max-md:order-2"><Cell label="업종 대비 · 20일" sub={summary.parent ? <>{summary.parent.name} {summary.parent.memberCount}사 평균 {formatPercent(summary.parent.avg20)}</> : '상위 업종 없음'}><span className={tone(summary.vsParent20)}>{formatPp(summary.vsParent20, 1)}</span></Cell></div>
    <div className="max-md:order-4"><Cell label="사업 근거" sub={`주의 ${summary.caveats}건 · 마지막 확인 ${shortDate(summary.lastChecked)}`}>{summary.verifiedCompanies}/{summary.memberCount} 원문 확인</Cell></div>
  </section>
}

/** 선택한 종목 띠 — 반대쪽 보기를 요약하고 그 보기로 넘어가는 버튼을 단다 */
function SelectedBand({ view, row, catalog, rows, days, onOther }: { view: string; row: ReturnType<typeof peerMemberRows>[number]; catalog: PeerCatalog; rows: ReturnType<typeof peerMemberRows>; days: number; onOther: () => void }) {
  const company = catalog.companies.find(item => item.code === row.code)
  const evidence = company ? companyEvidence(company) : null
  return <section aria-label="선택한 종목" className="flex flex-wrap items-center gap-x-4 gap-y-2 border bg-muted/40 px-4 py-3 max-md:flex-col max-md:items-start">
    <span className="text-caption text-muted-foreground">선택한 종목</span>
    <span className="font-semibold">{row.name} <span className="font-mono text-caption font-normal text-muted-foreground">{row.code}</span></span>
    <span className="min-w-0 flex-1 text-sm max-md:w-full">
      {view === 'research'
        ? row.rank === null ? '가격 없음 · 순위 없음' : <>그룹 내 {row.rank}위 · {days}일 <span className={tone(row.returns[days as 5])}>{formatPercent(row.returns[days as 5])}</span> · Peer 대비 20일 <span className={tone(row.excess20)}>{formatPp(row.excess20, 1)}</span>{rows.length < 2 && ' · 단독'}</>
        : <>이 그룹에 넣은 근거 · {row.products.join('·')}{evidence && <> · {evidence.verified ? `원문 ${evidence.verified}` : '미확인'} · <span className={evidence.caveats ? 'text-chart-warning' : ''}>주의 {evidence.caveats}</span></>}</>}
    </span>
    <span className="flex gap-2 max-md:self-end">
      <Button asChild variant="outline" size="sm"><Link to={`/analyze/${row.code}/summary`}>도시에 ›</Link></Button>
      <Button size="sm" onClick={onOther}>{view === 'research' ? '성과 비교로 보기 ›' : '사업 근거 보기 ›'}</Button>
    </span>
  </section>
}

/** 왼쪽 그룹 찾기 — 지금 업종의 사업군(20일 순) + 다른 업종. 검색은 이 목록만 거른다 */
function PeerFinder({ finder, groupId, query, onQuery, onPick }: { finder: ReturnType<typeof peerFinder>; groupId: string; query: string; onQuery: (value: string) => void; onPick: (id: string) => void }) {
  const row = (item: PeerListItem, indent = false, strong = false) => <li key={item.id}>
    <button type="button" aria-current={item.id === groupId ? 'true' : undefined} onClick={() => onPick(item.id)}
      className={cn('flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted/50', indent && 'pl-5', strong && 'font-semibold', item.id === groupId && 'bg-muted font-semibold')}>
      <span className="min-w-0 flex-1 truncate">{item.name}</span>
      <span className="shrink-0 text-caption tabular-nums text-muted-foreground">{item.memberCount}</span>
      <span className={cn('w-14 shrink-0 text-right font-mono text-caption tabular-nums', tone(item.return20))}>{formatPercent(item.return20)}</span>
    </button>
  </li>
  return <div className="space-y-2 py-2">
    <div className="relative px-3"><Search aria-hidden="true" className="pointer-events-none absolute left-6 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input type="search" aria-label="제품·기업으로 그룹 찾기" value={query} onChange={event => onQuery(event.target.value)} placeholder="제품·기업으로 그룹 찾기" className="h-9 pl-9" />
    </div>
    {finder.empty ? <div role="status" className="space-y-1 px-3 py-4 text-sm"><p>"{query}"이 들어간 그룹이 없습니다.</p><Button variant="link" className="h-auto p-0" onClick={() => onQuery('')}>검색어 지우기</Button></div> : <>
      <p className="flex justify-between px-3 text-caption text-muted-foreground"><span>업종 › 사업군</span><span>20일</span></p>
      {finder.open && <ul aria-label="지금 업종">
        {row(finder.open.industry, false, true)}
        {finder.open.children.map(item => row(item, true))}
      </ul>}
      {finder.others.length > 0 && <>
        {finder.open && <p className="border-t px-3 pt-2 text-caption text-muted-foreground">다른 업종</p>}
        <ul aria-label="다른 업종">{finder.others.flatMap(item => [row(item), ...item.children.map(child => row(child, true))])}</ul>
      </>}
    </>}
  </div>
}
