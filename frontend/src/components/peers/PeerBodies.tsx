import { useMemo } from 'react'
import { ExternalLink } from 'lucide-react'
import MultiLineChart, { type LineConfig } from '@/components/charts/MultiLineChart'
import PeriodToggle from '@/components/shared/PeriodToggle'
import { InfoTip } from '@/components/shared/InfoTip'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { normalizedPeerPath } from '@/lib/peerPerformance'
import { peerChildren, peerParent } from '@/lib/peerPresets'
import { PEER_DAYS, companyEvidence, sourceCheck, groupAverage, groupAveragePath, groupCompanies, peerMemberRows, type PeerDays, type PeerMemberRow } from '@/lib/peerFrame'
import { cn } from '@/lib/utils'
import { MOBILE_QUERY, useMediaQuery } from '@/hooks/useMediaQuery'
import { formatNumber, formatPercent, formatPp } from '@/utils/format'
import type { PeerCatalog, PeerGroup, PeerPriceSnapshot, PeerRuntime } from '@/types/peer'

const tone = (value: number | null | undefined) => value == null ? 'text-muted-foreground' : value > 0 ? 'text-up-ink' : value < 0 ? 'text-down-ink' : ''
const DAY_OPTIONS = PEER_DAYS.map(d => ({ value: String(d), label: `${d}일` }))
const shortDate = (iso: string | undefined) => iso ? iso.slice(5).replace('-', '/') : '-'

function Composite() {
  return <Badge variant="outline" className="h-5 px-1.5 text-[11px] font-normal">복합사업</Badge>
}
function EvidenceCount({ verified, caveats }: { verified: number; caveats: number }) {
  return <>{verified ? <span className="text-fact">원문 {verified}</span> : <span className="text-muted-foreground">미확인</span>} · <span className={caveats ? 'text-chart-warning' : 'text-muted-foreground'}>주의 {caveats}</span></>
}


/** 성과 비교 — 시작일=100 차트(선택 종목 상승색 굵게, 그룹 평균 점선) + 순위 표(마지막 줄 그룹 평균) */
export function PeerPerformanceBody({ data, group, rows, days, onDays, selected, onSelect, onResearch, onPick }: {
  data: PeerRuntime; group: PeerGroup; rows: PeerMemberRow[]; days: PeerDays; onDays: (value: string) => void
  selected: string | null; onSelect: (code: string) => void; onResearch: (code: string) => void; onPick: (id: string) => void
}) {
  const { catalog, prices } = data
  const phone = useMediaQuery(MOBILE_QUERY)
  const dates = prices.dates.slice(-days - 1)
  const paths = useMemo(() => rows.map(row => ({ row, path: normalizedPeerPath(prices, row.code, days) })), [rows, prices, days])
  const avgPath = useMemo(() => groupAveragePath(prices, rows.map(row => row.code), days), [prices, rows, days])
  const avg = Object.fromEntries(PEER_DAYS.map(d => [d, groupAverage(rows, d)])) as Record<PeerDays, ReturnType<typeof groupAverage>>
  const chartData = dates.map((time, index) => ({ time, group: avgPath?.[index], ...Object.fromEntries(paths.map(({ row, path }) => [`stock_${row.code}`, path?.[index]])) }))
  const many = rows.length > 8
  // 시안 규칙: 회색 시리즈 · 고른 종목만 글자색 굵은 선 · 평균 점선 · 선 끝 라벨의 값만 등락색
  const tone = (v: number | null | undefined) => v == null || v === 0 ? 'flat' as const : v > 0 ? 'up' as const : 'down' as const
  const end = (name: string, v: number | null | undefined, strong = false) => many && !strong ? undefined : { name, value: formatPercent(v ?? null), tone: tone(v), strong }
  const lines: LineConfig[] = [
    ...paths.filter(({ path, row }) => path && row.code !== selected).map(({ row }) => ({ key: `stock_${row.code}`, label: row.name, endLabel: end(row.name, row.returns[days]), color: '--series', lineWidth: 1 })),
    ...(avgPath ? [{ key: 'group', label: '그룹 평균', endLabel: end('그룹 평균', avg[days].value, true), color: '--ink-2', lineWidth: 2, lineStyle: 2 }] : []),
    ...paths.filter(({ path, row }) => path && row.code === selected).map(({ row }) => ({ key: `stock_${row.code}`, label: row.name, endLabel: end(row.name, row.returns[days], true), color: '--ink', lineWidth: 3 })),
  ]
  const missing = rows.filter(row => row.returns[days] === null)
  const children = peerChildren(catalog, group.id)
  return <div className="space-y-4">
    <section aria-label="구성 종목 성과" className="space-y-3 border bg-card p-3 md:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1 text-section font-semibold">구성 종목 성과 <span className="text-caption font-normal text-muted-foreground">{shortDate(dates[0])} = 100</span>
          <InfoTip label="가격 기준 설명">네이버 정규장 종가({prices.asOf}) 기준 탐색용 가격변동률입니다. 그룹 평균은 기간 시작 동일가중이며, 기업행사 조정은 검증하지 않았습니다. 자동 신호는 보류 중입니다({data.signalHoldReason}).</InfoTip>
        </h2>
        <PeriodToggle value={String(days)} onChange={onDays} options={DAY_OPTIONS} />
      </div>
      {missing.length > 0 && <p role="status" className="text-caption text-chart-warning">가격 없는 종목 {missing.length}개는 표에 '-'로 두고 차트와 그룹 평균에서 뺐습니다 · 평균 {avg[days].covered}/{rows.length}사</p>}
      {lines.length ? <MultiLineChart data={chartData} lines={lines} showLegend={false} endLabels={phone ? undefined : 150} showLastValues={false} showLineTooltip onLineClick={key => { if (key.startsWith('stock_')) onSelect(key.slice(6)) }} height={300} formatValue={formatNumber} />
        : <p role="status" className="py-10 text-center text-sm text-muted-foreground">이 기간에 그릴 가격이 없습니다.</p>}
      <Table aria-label="구성 종목 성과표" className="max-md:hidden">
        <TableHeader><TableRow>
          <TableHead className="w-12">순위</TableHead><TableHead>종목</TableHead>
          {PEER_DAYS.map(d => <TableHead key={d} className="text-right">{d}일{d === days && ' ↓'}</TableHead>)}
          <TableHead className="text-right">Peer 대비 · 20일</TableHead><TableHead className="text-right">사업 근거</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.map(row => <TableRow key={row.code} data-state={row.code === selected ? 'selected' : undefined} className={cn(row.code === selected && 'bg-up/5 data-[state=selected]:bg-up/5')}>
            <TableCell className="tabular-nums">{row.rank ?? '-'}</TableCell>
            <TableCell className="whitespace-normal"><button type="button" className="text-left hover:underline" aria-pressed={row.code === selected} onClick={() => onSelect(row.code)}><span className="font-semibold">{row.name}</span></button>
              {row.composite && <span className="ml-1.5"><Composite /></span>}<span className="ml-1.5 text-caption text-muted-foreground">{row.products.join('·')}</span></TableCell>
            {PEER_DAYS.map(d => <TableCell key={d} className={cn('text-right font-mono tabular-nums', tone(row.returns[d]))}>{formatPercent(row.returns[d])}</TableCell>)}
            <TableCell className={cn('text-right font-mono tabular-nums', tone(row.excess20))}>{formatPp(row.excess20, 1)}</TableCell>
            <TableCell className="text-right text-caption"><button type="button" className="hover:underline" onClick={() => onResearch(row.code)} aria-label={`${row.name} 사업 근거 보기`}><EvidenceCount verified={row.verified} caveats={row.caveats} /> ›</button></TableCell>
          </TableRow>)}
          <TableRow className="hover:bg-transparent">
            <TableCell /><TableCell>그룹 평균{avg[days].covered < rows.length && <span className="ml-1 text-caption text-muted-foreground">{avg[days].covered}/{rows.length}사</span>}</TableCell>
            {PEER_DAYS.map(d => <TableCell key={d} className={cn('text-right font-mono tabular-nums', tone(avg[d].value))}>{formatPercent(avg[d].value)}</TableCell>)}
            <TableCell className="text-right text-muted-foreground">-</TableCell><TableCell />
          </TableRow>
        </TableBody>
      </Table>
      <ol aria-label="구성 종목 목록" className="divide-y border-t md:hidden">
        {rows.map(row => <li key={row.code}>
          <button type="button" onClick={() => onSelect(row.code)} aria-pressed={row.code === selected} className={cn('flex w-full items-center gap-3 px-1 py-2.5 text-left', row.code === selected && 'bg-up/5')}>
            <span className="w-5 shrink-0 text-caption tabular-nums text-muted-foreground">{row.rank ?? '-'}</span>
            <span className="min-w-0 flex-1"><span className="block font-semibold">{row.name}{row.composite && <span className="ml-1"><Composite /></span>}</span><span className="block truncate text-caption text-muted-foreground">{row.products.join('·')}</span></span>
            <span className="shrink-0 text-right"><span className={cn('block font-mono text-sm tabular-nums', tone(row.returns[days]))}>{formatPercent(row.returns[days])}</span>{days !== 20 && <span className="block text-caption text-muted-foreground">20일 <span className={tone(row.returns[20])}>{formatPercent(row.returns[20])}</span></span>}</span>
          </button>
        </li>)}
        <li className="flex justify-between px-1 py-2.5 text-sm"><span>그룹 평균</span><span className={cn('font-mono tabular-nums', tone(avg[days].value))}>{formatPercent(avg[days].value)}</span></li>
      </ol>
    </section>
    {children.length > 0 && <section aria-label="세부 사업군" className="space-y-2 border p-3 md:p-4">
      <h2 className="text-card-title font-semibold">세부 사업군</h2>
      <Table><TableHeader><TableRow><TableHead>사업군</TableHead><TableHead className="text-right">구성</TableHead>{PEER_DAYS.map(d => <TableHead key={d} className="text-right">{d}일</TableHead>)}</TableRow></TableHeader>
        <TableBody>{children.map(child => {
          const childRows = peerMemberRows(catalog, prices, child.id, days)
          return <TableRow key={child.id}>
            <TableCell><button type="button" className="text-left hover:underline" onClick={() => onPick(child.id)}>{child.name}</button></TableCell>
            <TableCell className="text-right tabular-nums">{childRows.length}사</TableCell>
            {PEER_DAYS.map(d => { const v = groupAverage(childRows, d).value; return <TableCell key={d} className={cn('text-right font-mono tabular-nums', tone(v))}>{formatPercent(v)}</TableCell> })}
          </TableRow>
        })}</TableBody>
      </Table>
    </section>}
  </div>
}

/** 사업 근거 — 그룹을 묶은 기준 + 성과 순위와 같은 순서의 카드. 선택한 종목만 펼친다 */
export function PeerResearchBody({ catalog, group, rows, days, selected, onSelect, onPick, onPerformance }: {
  catalog: PeerCatalog; group: PeerGroup; rows: PeerMemberRow[]; days: PeerDays; selected: string | null
  onSelect: (code: string) => void; onPick: (id: string) => void; onPerformance: (code: string) => void
}) {
  return <div className="space-y-4">
    <section aria-label="이 그룹을 묶은 기준" className="space-y-1 border bg-card p-3 md:p-4">
      <h2 className="text-section font-semibold">이 그룹을 묶은 기준 <span className="text-caption font-normal text-muted-foreground">{group.scope === 'product' ? '제품·공정' : '밸류체인'} · {rows.length}사</span></h2>
      <p className="text-sm">{group.interpretation}</p>
    </section>
    <section aria-label="구성 종목" className="space-y-2">
      <h2 className="text-caption text-muted-foreground">구성 종목</h2>
      <ol className="divide-y border bg-card">{rows.map((row, index) => {
        const company = catalog.companies.find(item => item.code === row.code)!
        const open = row.code === selected
        const others = company.groupIds.filter(id => id !== group.id && id !== peerParent(catalog, group.id))
        return <li key={row.code} className={cn(open && 'bg-surface-2')}>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-3 md:px-4">
            <span className="w-5 text-caption tabular-nums text-muted-foreground">{row.rank ?? index + 1}</span>
            <button type="button" aria-expanded={open} onClick={() => onSelect(row.code)} className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 text-left">
              <span className="font-semibold">{row.name}</span><span className="font-mono text-caption text-muted-foreground">{row.code}</span>
              {row.composite && <Composite />}<span className="text-caption text-muted-foreground">{row.products.join('·')}</span>
            </button>
            <button type="button" className="shrink-0 text-caption hover:underline" onClick={() => onPerformance(row.code)} aria-label={`${row.name} 성과 비교로 보기`}>{days}일 <span className={cn('font-mono', tone(row.returns[days]))}>{formatPercent(row.returns[days])}</span> · 성과 ›</button>
          </div>
          {open ? <div className="grid gap-4 px-3 pb-4 md:grid-cols-3 md:px-4">
            <div className="min-w-0 space-y-2">
              <p className="text-caption text-muted-foreground">왜 이 그룹인가 · 확인 {shortDate(company.asOf)}</p>
              <ul className="space-y-2 text-sm">{company.sources.map((source, i) => <li key={`${source.url}-${i}`}>
                <p>{source.claim}</p>
                <p className="flex flex-wrap items-center gap-2 text-caption">
                  {sourceCheck(source.verification) === 'original' ? <span className="text-fact">원문 확인</span> : <span className="text-muted-foreground">{sourceCheck(source.verification) === 'link' ? '링크만' : '요약만 확인'}</span>}
                  <a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">{new URL(source.url).hostname}<ExternalLink className="size-3" aria-hidden="true" /><span className="sr-only"> 새 창</span></a>
                </p>
              </li>)}</ul>
            </div>
            <div className="min-w-0 space-y-2">
              <p className="text-caption text-chart-warning">주의 {company.caveats.length}</p>
              {company.caveats.length ? <ul className="list-disc space-y-1 pl-4 text-sm">{company.caveats.map((text, i) => <li key={i}>{text}</li>)}</ul> : <p className="text-sm text-muted-foreground">-</p>}
            </div>
            <div className="min-w-0 space-y-2">
              <p className="text-caption text-muted-foreground">같이 들어간 다른 사업군</p>
              {others.length ? <div className="flex flex-wrap gap-1">{others.map(id => <Button key={id} variant="outline" size="sm" className="h-auto min-h-8 max-w-full shrink whitespace-normal text-caption" onClick={() => onPick(id)}>{catalog.groups.find(item => item.id === id)?.name ?? id}</Button>)}</div> : <p className="text-sm text-muted-foreground">-</p>}
            </div>
          </div> : <p className="truncate px-3 pb-3 pl-11 text-caption md:px-4 md:pl-12"><EvidenceCount verified={row.verified} caveats={row.caveats} />{company.caveats[0] && <span className="text-muted-foreground"> · {company.caveats[0]}</span>}</p>}
        </li>
      })}</ol>
    </section>
  </div>
}

const topLevel = (catalog: PeerCatalog) => catalog.groups.filter(group => !peerParent(catalog, group.id))

/** 업종 전체 · 성과 비교 — 업종(상위 그룹) 평균 경로와 표 */
export function PeerIndustriesBody({ catalog, snapshot, days, onDays, onPick }: { catalog: PeerCatalog; snapshot: PeerPriceSnapshot; days: PeerDays; onDays: (value: string) => void; onPick: (id: string) => void }) {
  const items = useMemo(() => topLevel(catalog).map(group => {
    const rows = peerMemberRows(catalog, snapshot, group.id, days)
    return { group, rows, avg: Object.fromEntries(PEER_DAYS.map(d => [d, groupAverage(rows, d)])) as Record<PeerDays, ReturnType<typeof groupAverage>>, path: groupAveragePath(snapshot, rows.map(row => row.code), days) }
  }).sort((a, b) => (b.avg[days].value ?? -Infinity) - (a.avg[days].value ?? -Infinity)), [catalog, snapshot, days])
  const dates = snapshot.dates.slice(-days - 1)
  // 회색 시리즈 · 1위 업종만 글자색 굵은 선 · 상위 3곳만 선 끝 라벨(값은 등락색)
  const lines: LineConfig[] = items.filter(item => item.path).map((item, index) => {
    const v = item.avg[days].value
    return { key: item.group.id, label: item.group.name, color: index === 0 ? '--ink' : '--series', lineWidth: index === 0 ? 3 : 1,
      endLabel: index < 3 ? { name: item.group.name, value: formatPercent(v), tone: v == null || v === 0 ? 'flat' as const : v > 0 ? 'up' as const : 'down' as const, strong: index === 0 } : undefined }
  }).reverse()
  const phone = useMediaQuery(MOBILE_QUERY)
  const chartData = dates.map((time, index) => ({ time, ...Object.fromEntries(items.map(item => [item.group.id, item.path?.[index]])) }))
  return <section aria-label="업종 간 비교" className="space-y-3 border bg-card p-3 md:p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="flex items-center gap-1 text-section font-semibold">업종 간 비교 <span className="text-caption font-normal text-muted-foreground">{shortDate(dates[0])} = 100</span>
        <InfoTip label="업종 평균 설명">업종마다 구성 종목을 기간 시작에 동일가중한 평균입니다. 공식 업종지수가 아니며 한 기업이 여러 업종에 들 수 있습니다.</InfoTip>
      </h2>
      <PeriodToggle value={String(days)} onChange={onDays} options={DAY_OPTIONS} />
    </div>
    {lines.length > 0 && <MultiLineChart data={chartData} lines={lines} showLegend={false} endLabels={phone ? undefined : 150} showLastValues={false} showLineTooltip onLineClick={onPick} height={280} formatValue={formatNumber} />}
    <Table aria-label="업종 간 비교 성과표">
      <TableHeader><TableRow><TableHead>업종</TableHead><TableHead className="text-right">구성</TableHead>{PEER_DAYS.map(d => <TableHead key={d} className="text-right">{d}일{d === days && ' ↓'}</TableHead>)}</TableRow></TableHeader>
      <TableBody>{items.map(item => <TableRow key={item.group.id}>
        <TableCell><button type="button" className="text-left font-medium hover:underline" onClick={() => onPick(item.group.id)}>{item.group.name}</button>{peerChildren(catalog, item.group.id).length > 0 && <span className="ml-1.5 text-caption text-muted-foreground">사업군 {peerChildren(catalog, item.group.id).length}</span>}</TableCell>
        <TableCell className="text-right tabular-nums">{item.rows.length}사{item.avg[days].covered < item.rows.length && <span className="ml-1 text-caption text-muted-foreground">({item.avg[days].covered})</span>}</TableCell>
        {PEER_DAYS.map(d => <TableCell key={d} className={cn('text-right font-mono tabular-nums', tone(item.avg[d].value))}>{formatPercent(item.avg[d].value)}</TableCell>)}
      </TableRow>)}</TableBody>
    </Table>
  </section>
}

/** 업종 전체 · 사업 근거 — 업종별 묶은 기준과 원문 확인 현황 */
export function PeerIndustriesResearch({ catalog, onPick }: { catalog: PeerCatalog; onPick: (id: string) => void }) {
  return <section aria-label="업종별 사업 근거" className="border">
    <ul className="divide-y">{topLevel(catalog).map(group => {
      const companies = groupCompanies(catalog, group.id)
      const evidence = companies.map(companyEvidence)
      return <li key={group.id}><button type="button" onClick={() => onPick(group.id)} className="block w-full space-y-1 px-3 py-3 text-left hover:bg-muted/40 md:px-4">
        <span className="flex flex-wrap items-baseline gap-x-2"><span className="font-semibold">{group.name}</span><span className="text-caption text-muted-foreground">{companies.length}사 · 원문 확인 {evidence.filter(e => e.verified > 0).length}/{companies.length} · 주의 {evidence.reduce((sum, e) => sum + e.caveats, 0)}</span></span>
        <span className="line-clamp-2 block text-sm text-muted-foreground">{group.interpretation}</span>
      </button></li>
    })}</ul>
  </section>
}
