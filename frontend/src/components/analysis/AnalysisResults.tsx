import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { type ColumnDef, type SortingState, flexRender, getCoreRowModel, getSortedRowModel, useReactTable } from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ExternalLink, FolderPlus } from 'lucide-react'
import { toast } from 'sonner'
import { GroupPicker } from '@/components/follow/GroupPicker'
import { useAddMember } from '@/hooks/useGroups'
import CandlestickChart from '@/components/charts/CandlestickChart'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAnalysisChart } from '@/hooks/useMarketAnalysis'
import { formatKrw, formatNumber } from '@/utils/format'
import { checkValue, evidenceValue, EXCLUSION_LABELS, strategyCheck } from '@/components/analysis/strategyEvidence'
import type { AnalysisCandidate, AnalysisResult, StrategyDefinition } from '@/components/analysis/types'
import { CandidateDiscovery } from '@/components/analysis/CandidateDiscovery'
import { DiscoveryRecommendations } from '@/components/analysis/DiscoveryLibrary'

const CHECK_LABELS: Record<string, string> = { market_cap: '시가총액', ihs: '역헤드앤숄더', pattern: '패턴', neckline_breakout: '넥라인 돌파', high52: '52주 신고가', high_52w: '52주 신고가', ma_hold: '이동평균 유지', ma: '이동평균 유지', event_order: '사건 순서', coverage: '데이터 범위', price_adjustment: '수정주가', calendar: '거래일 달력' }
function CandidateChart({ runId, candidate, maPeriod, catalog = false, definitions = [] }: { runId: string; candidate: AnalysisCandidate; maPeriod: number; catalog?: boolean; definitions?: StrategyDefinition[] }) {
  const chart = useAnalysisChart(runId, candidate.code)
  const addMember = useAddMember()
  return <Card id="discovery-candidate-preview" className="min-w-0 scroll-mt-4">
    <CardHeader className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="text-section font-semibold">{candidate.name}</h3><p className="mt-1 text-caption text-muted-foreground">{candidate.code} · 시가총액 {formatKrw(candidate.market_cap)}</p></div><div className="flex flex-wrap items-start gap-2"><GroupPicker label="묶음에 추가" icon={<FolderPlus className="size-3.5" />} busy={addMember.isPending} onPick={async id => { const detail = await addMember.mutateAsync({ groupId: id, stock_code: candidate.code }); toast.success(`${candidate.name}을(를) ‘${detail.name}’에 추가했습니다.`) }} /><CandidateDiscovery runId={runId} candidate={candidate} /></div></div>
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium">차트와 충족 근거</p><Button variant="ghost" size="sm" asChild><Link to={`/analyze/${candidate.code}/summary`}>기업 개요 <ExternalLink className="size-3.5" /></Link></Button></div>
    </CardHeader>
    <CardContent className="min-w-0 space-y-4">
      {chart.isPending && <Skeleton className="h-80 w-full" />}
      {chart.isError && <ErrorState message="분석에 사용한 차트를 불러오지 못했습니다." onRetry={() => chart.refetch()} />}
      {chart.data && (chart.data.prices.length ? <>
        <div role="img" aria-label={catalog ? `${candidate.name} 일봉과 확인된 전략 신호 날짜` : `${candidate.name} 일봉과 ${maPeriod}일 이동평균, 넥라인, 확인된 패턴 날짜`}>
          <CandlestickChart data={chart.data.prices} height={280}
            markers={chart.data.markers.map(marker => ({ time: marker.time, direction: marker.kind === 'head' || marker.kind.includes('shoulder') ? 'up' : 'down', text: marker.label }))}
            overlays={[...(chart.data.ma.length ? [{ id: 'ma', title: `SMA${maPeriod}`, token: '--chart-1', data: chart.data.ma }] : []), ...(chart.data.neckline.length ? [{ id: 'neckline', title: '넥라인', token: '--chart-2', data: chart.data.neckline, dashed: true }] : [])]} />
        </div>
        <p className="text-caption text-muted-foreground">일봉{chart.data.ma.length > 0 && ` · SMA${maPeriod}`}{chart.data.neckline.length > 0 && ' · 넥라인(점선)'}. 마커는 이 실행에서 확인한 날짜를 표시합니다.</p>
        {!!chart.data.markers.length && <div className="flex flex-wrap gap-2">{chart.data.markers.map((marker, index) => <Badge key={`${marker.time}-${index}`} variant="outline" className="font-normal">{marker.label} {marker.time} · {formatNumber(marker.price)}원</Badge>)}</div>}
      </> : <p className="text-sm text-muted-foreground">이 실행의 차트 자료가 없습니다.</p>)}
      {catalog || definitions.length > 0 ? <Table aria-label={`${candidate.name} 조건별 계산 값`}>
        <TableHeader><TableRow><TableHead>조건</TableHead><TableHead>판정</TableHead><TableHead className="text-right">계산 값</TableHead><TableHead className="text-right">비교 기준</TableHead><TableHead>판정일</TableHead><TableHead className="text-right">순위</TableHead></TableRow></TableHeader>
        <TableBody>{Object.entries(candidate.checks ?? {}).map(([id, value]) => {
          const check = strategyCheck(value)
          return <TableRow key={id}><TableCell className="max-w-64 whitespace-normal">{check.label ?? definitions.find(item => item.id === id)?.label ?? CHECK_LABELS[id] ?? id}{check.estimated && <span className="block text-caption text-muted-foreground">일봉 기반 추정</span>}</TableCell><TableCell className="max-w-64 whitespace-normal">{checkValue(value)}</TableCell><TableCell className="text-right tabular-nums">{evidenceValue(check.value)}</TableCell><TableCell className="text-right tabular-nums">{evidenceValue(check.reference)}</TableCell><TableCell>{check.date ?? '—'}</TableCell><TableCell className="text-right tabular-nums">{check.rank == null ? '—' : `${formatNumber(check.rank)}위`}</TableCell></TableRow>
        })}</TableBody>
      </Table> : <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">{Object.entries(candidate.checks ?? {}).map(([name, value]) => <div key={name} className="flex justify-between gap-3 text-caption"><dt className="text-muted-foreground">{CHECK_LABELS[name] ?? name}</dt><dd className="text-right">{checkValue(value)}</dd></div>)}</dl>}
    </CardContent>
  </Card>
}

function CandidateTable({ items, selected, onSelect, signals }: { items: AnalysisCandidate[]; selected: string; onSelect: (code: string) => void; signals: (item: AnalysisCandidate) => ReactNode }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'market_cap', desc: true }])
  const columns: ColumnDef<AnalysisCandidate>[] = [
    { id: 'name', accessorKey: 'name', header: '종목', enableSorting: false, cell: ({ row }) => <span className="block space-y-1">
      <span className="flex flex-wrap items-center gap-2"><span className="font-semibold">{row.original.name}</span>{row.original.status === 'provisional' && <Badge variant="outline" className="font-normal text-hypothesis">잠정 후보</Badge>}</span>
      <span className="block text-caption text-muted-foreground">{row.original.code}</span>
      <span className="block space-y-1 text-caption">{signals(row.original)}</span>
    </span> },
    { id: 'market_cap', accessorFn: item => item.market_cap ?? undefined, sortUndefined: 'last', sortDescFirst: true,
      header: ({ column }) => { const sorted = column.getIsSorted(); const Icon = sorted === 'desc' ? ArrowDown : sorted === 'asc' ? ArrowUp : ArrowUpDown
        return <Button variant="ghost" size="sm" className="-mr-2 h-7 gap-1 px-2" aria-label={`시가총액 정렬${sorted === 'desc' ? ' · 큰 순' : sorted === 'asc' ? ' · 작은 순' : ''}`} onClick={column.getToggleSortingHandler()}>시가총액<Icon className="size-3.5" aria-hidden="true" /></Button> },
      cell: ({ row }) => <span className="tabular-nums">{formatKrw(row.original.market_cap)}</span> },
  ]
  const table = useReactTable({ data: items, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getRowId: item => item.code })
  return <div className="max-h-72 overflow-y-auto lg:max-h-[min(65dvh,44rem)]">
    <Table aria-label="후보 종목 목록">
      <TableHeader className="sticky top-0 z-10 bg-card">{table.getHeaderGroups().map(group => <TableRow key={group.id}>{group.headers.map(header => <TableHead key={header.id} className={header.column.id === 'market_cap' ? 'text-right' : undefined}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}</TableRow>)}</TableHeader>
      <TableBody>{table.getRowModel().rows.map(row => <TableRow key={row.id} tabIndex={0} role="button" aria-pressed={row.id === selected} data-state={row.id === selected ? 'selected' : undefined} className="cursor-pointer" onClick={() => onSelect(row.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(row.id) } }}>
        {row.getVisibleCells().map(cell => <TableCell key={cell.id} className={cell.column.id === 'market_cap' ? 'text-right align-top' : 'whitespace-normal align-top'}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}
      </TableRow>)}</TableBody>
    </Table>
  </div>
}

export function AnalysisResults({ runId, result, onOpen, warnings = result.warnings }: { runId: string; result: AnalysisResult; onOpen: (id: string) => void; warnings?: string[] }) {
  const [params, setParams] = useSearchParams()
  const candidate = result.items.find(item => item.code === params.get('candidate')) ?? result.items[0]
  const catalog = result.spec.mode === 'catalog'
  const definitions = result.strategy_definitions ?? []
  const counts = result.counts
  const signals = (item: AnalysisCandidate): ReactNode => <>{catalog ? <>{result.spec.expression && <span className="block">복합 조건식 · {checkValue(item.checks.expression)}</span>}{(result.spec.strategy_conditions ?? []).slice(0, 2).map(condition => { const check = strategyCheck(item.checks[condition.strategy_id]); return <span key={condition.strategy_id} className="block">{check.label ?? definitions.find(definition => definition.id === condition.strategy_id)?.label ?? condition.strategy_id}{check.rank != null ? ` · ${formatNumber(check.rank)}위` : check.date ? ` · ${check.date}` : ''}</span> })}{(result.spec.strategy_conditions?.length ?? 0) > 2 && <span className="block text-muted-foreground">외 {formatNumber(result.spec.strategy_conditions!.length - 2)}개 조건</span>}</> : <>{item.breakout_date && <span className="block">넥라인 돌파 · {item.breakout_date}</span>}{item.high52_date && <span className="block">52주 신고가 · {item.high52_date}</span>}</>}</>
  const inconclusive = counts.matched === 0 && counts.excluded > 0
  const exclusionCounts = Object.entries(result.excluded.reduce<Record<string, number>>((groups, item) => {
    groups[item.reason] = (groups[item.reason] ?? 0) + 1
    return groups
  }, {})).sort((a, b) => b[1] - a[1])
  function select(code: string) {
    setParams(previous => { const next = new URLSearchParams(previous); next.set('candidate', code); return next }, { replace: true, preventScrollReset: true })
    if (window.matchMedia('(max-width: 1023px)').matches) document.getElementById('discovery-candidate-preview')?.scrollIntoView({ block: 'start' })
  }
  return <section aria-label="분석 결과" className="space-y-4">
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1"><h2 className="text-section font-semibold">{inconclusive ? '통과 확인 0개 · 일부 종목 미평가' : `${formatNumber(counts.matched)}개 후보 종목`}</h2><p className="text-caption text-muted-foreground">{result.as_of} 기준 · 대상 {formatNumber(counts.universe)}개 · 조건 탈락 {formatNumber(Math.max(0, counts.evaluated - counts.matched))}개</p></div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption">{counts.excluded > 0 && <span className="font-medium text-hypothesis">미평가 {formatNumber(counts.excluded)}개 · 자료 부족 또는 계산 오류</span>}{result.items.some(item => item.status === 'provisional') && <span className="text-hypothesis">잠정 후보의 미검증 항목을 확인해 주세요.</span>}{warnings.length > 0 && <span className="text-muted-foreground">자료·조건 확인 {formatNumber(warnings.length)}건</span>}</div>
      {!!result.unsupported_conditions?.length && <p className="text-sm text-hypothesis">요청 중 아직 평가하지 못한 조건: {result.unsupported_conditions.join(' · ')}</p>}
      {inconclusive && <p className="rounded-lg bg-hypothesis/10 p-3 text-sm">평가한 종목에서는 통과를 확인하지 못했습니다. 미평가 종목이 있어 전체 대상에 해당 종목이 없다고 판단할 수 없습니다.</p>}
    </div>

    {candidate ? <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(260px,0.75fr)_minmax(0,1.65fr)]">
      <section aria-label="후보 목록" className="min-w-0 rounded-xl bg-card p-2 lg:sticky lg:top-4">
        <p className="px-3 pb-2 pt-1 text-caption text-muted-foreground">종목을 선택해 차트와 근거를 확인하세요.</p>
        <CandidateTable items={result.items} selected={candidate.code} onSelect={select} signals={signals} />
      </section>
      <div className="min-w-0 space-y-3"><CandidateChart key={candidate.code} runId={runId} candidate={candidate} maPeriod={result.spec.ma_period} catalog={catalog} definitions={definitions} />
        <Collapsible className="rounded-xl bg-card p-3"><CollapsibleTrigger asChild><Button variant="ghost" className="h-auto w-full justify-between whitespace-normal text-left">{candidate.name}에서 확인한 신호로 다른 종목 찾기<ChevronDown className="size-4 shrink-0" /></Button></CollapsibleTrigger><CollapsibleContent className="pt-3"><DiscoveryRecommendations compact key={candidate.code} runId={runId} stockCode={candidate.code} onOpen={onOpen} /></CollapsibleContent></Collapsible>
      </div>
    </div> : <Card><CardContent className="space-y-2 py-8 text-center"><p className="font-medium">{counts.evaluated === 0 ? '평가 가능한 종목이 없습니다.' : '평가한 종목 중 모든 조건을 통과한 종목이 없습니다.'}</p><p className="text-sm text-muted-foreground">위에서 조건을 바꾸거나 검색 범위를 ‘이전 검색 대상 전체’로 넓혀 다시 찾아보세요.</p></CardContent></Card>}

    {(counts.excluded > 0 || warnings.length > 0) && <Collapsible className="rounded-xl bg-card px-4 py-2"><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="h-auto w-full justify-between whitespace-normal text-left">자료 범위·미평가 사유 확인<ChevronDown className="size-4 shrink-0" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-4 pb-3 pt-3">
      <p className="text-caption text-muted-foreground">미평가 종목은 조건 탈락에 포함하지 않습니다. 조건 탈락에는 시가총액 등 앞선 조건에서 제외된 종목도 포함됩니다.</p>
      {warnings.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">{warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
      {exclusionCounts.length > 0 && <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">{exclusionCounts.map(([reason, count]) => <div key={reason} className="flex gap-2"><dt>{EXCLUSION_LABELS[reason] ?? reason}</dt><dd>{formatNumber(count)}종목</dd></div>)}</dl>}
      {counts.excluded > 0 && <p className="text-caption text-muted-foreground">같은 데이터로 다시 실행해도 누락된 시세 이력은 채워지지 않습니다. 기업 조사의 재무·공시 준비와는 별도의 수집 범위입니다.</p>}
      {!!result.excluded.length && <div className="max-h-72 overflow-y-auto"><Table><TableHeader><TableRow><TableHead>미평가 종목</TableHead><TableHead>사유와 보유 기간</TableHead></TableRow></TableHeader><TableBody>{result.excluded.map((item, index) => <TableRow key={`${item.code}-${index}`}><TableCell><Link className="hover:underline" to={`/analyze/${item.code}/summary`}>{item.name ?? item.code}</Link>{item.name && <span className="ml-2 text-caption text-muted-foreground">{item.code}</span>}</TableCell><TableCell className="whitespace-normal">{EXCLUSION_LABELS[item.reason] ?? item.reason}{item.conditions?.map(condition => <p key={condition.strategy_id} className="text-caption text-muted-foreground">{condition.label}: {EXCLUSION_LABELS[condition.reason] ?? condition.reason}</p>)}{item.first_date && item.last_date && <p className="text-caption text-muted-foreground">보유 기간 {item.first_date} ~ {item.last_date}</p>}{item.reason === 'insufficient_history' && item.required_start && <p className="text-caption text-muted-foreground">필요 시작일 {item.required_start}</p>}</TableCell></TableRow>)}</TableBody></Table></div>}
    </CollapsibleContent></Collapsible>}
    {definitions.length > 0 && <Collapsible className="rounded-xl bg-card px-4 py-2"><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="w-full justify-between">적용한 전략의 계산 기준<ChevronDown className="size-4" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-4 py-3">{definitions.map(definition => <div key={definition.id} className="space-y-2"><h3 className="text-sm font-medium">{definition.label}</h3><p className="text-caption text-muted-foreground">{definition.description}</p><p className="break-words text-caption text-muted-foreground">{definition.formula}</p><dl className="flex flex-wrap gap-x-5 gap-y-1 text-caption">{Object.entries(result.spec.strategy_conditions?.find(condition => condition.strategy_id === definition.id)?.params ?? {}).map(([key, value]) => <div key={key} className="flex gap-1"><dt>{definition.parameters[key]?.label ?? key}:</dt><dd>{evidenceValue(value)}</dd></div>)}</dl></div>)}</CollapsibleContent></Collapsible>}
  </section>
}
