import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTheme } from 'next-themes'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, TableCaption } from '@/components/ui/table'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import PeriodToggle from '@/components/shared/PeriodToggle'
import MultiLineChart, { type LineConfig } from '@/components/charts/MultiLineChart'
import { PeerPerformancePanel } from '@/components/peers/PeerPerformancePanel'
import { computePeerPerformance } from '@/lib/peerPerformance'
import { PEER_PRESETS } from '@/lib/peerPresets'
import { navigatePeerLayer, peerIndustry, peerLayer, peerLayerGroups, type PeerLayer } from '@/lib/peerNavigation'
import { formatPercent, formatPp, formatNumber } from '@/utils/format'
import type { PeerCatalog, PeerPriceSnapshot } from '@/types/peer'

const labels = { industries: '1. 업종 간 비교', businesses: '2. 세부 사업군 간 비교', peers: '3. 사업군 내 Peer 비교' }
const color = (value: number | null) => value === null ? 'text-muted-foreground' : value > 0 ? 'text-up' : value < 0 ? 'text-down' : ''

export function PeerComparisonWorkspace({ catalog, snapshot }: { catalog: PeerCatalog; snapshot: PeerPriceSnapshot }) {
  const [params, setParams] = useSearchParams()
  const layer = peerLayer(params)
  const industry = peerIndustry(catalog, params)
  const industryGroup = catalog.groups.find(group => group.id === industry)
  const group = catalog.groups.find(group => group.id === params.get('group'))
  const go = (target: PeerLayer, sector = industry, member?: string) => setParams(previous => navigatePeerLayer(previous, target, target === 'industries' ? undefined : sector, member))
  const firstBusiness = peerLayerGroups(catalog, 'businesses', industry)[0]?.id
  return <div className="space-y-4">
    <nav aria-label="비교 단계" className="flex flex-wrap gap-2">
      {(Object.entries(labels) as [PeerLayer, string][]).map(([value, label]) => <Button key={value} variant={layer === value ? 'secondary' : 'outline'} aria-current={layer === value ? 'step' : undefined} onClick={() => go(value, industry, value === 'peers' ? group?.id ?? firstBusiness ?? industryGroup?.id : undefined)}>{label}</Button>)}
    </nav>
    <p className="text-caption text-muted-foreground" aria-label="현재 비교 경로">업종 전체{layer !== 'industries' && ` / ${industry === 'all' ? '전체 사업군' : industryGroup?.name ?? '알 수 없는 업종'}`}{layer === 'peers' && group && ` / ${group.name}`}</p>
    {!['industries', 'businesses', 'peers'].includes(layer) ? <div role="status"><p>존재하지 않는 비교 단계입니다.</p><Button variant="outline" onClick={() => go('industries')}>업종 비교로 돌아가기</Button></div>
      : layer === 'peers' ? <>
        {params.get('layer') === 'peers' && <div className="max-w-sm"><label htmlFor="comparison-business" className="mb-1 block text-caption">비교할 사업군</label><Select value={group?.id ?? '__unknown__'} onValueChange={id => go('peers', industry, id)}><SelectTrigger id="comparison-business" className="w-full"><SelectValue /></SelectTrigger><SelectContent>
          {!group && <SelectItem value="__unknown__" disabled>사업군을 선택해 주세요</SelectItem>}
          {[...new Map([...peerLayerGroups(catalog, 'businesses', industry), ...(group ? [group] : [])].map(item => [item.id, item])).values()].map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
        </SelectContent></Select></div>}
        {params.get('layer') === 'peers' && !params.has('group') ? <p role="status">비교할 사업군을 선택해 주세요.</p> : <PeerPerformancePanel catalog={catalog} snapshot={snapshot} />}
      </>
        : <GroupComparison catalog={catalog} snapshot={snapshot} layer={layer} industry={industry} onDrill={id => layer === 'industries' ? go('businesses', id) : go('peers', industry === 'all' ? peerIndustry(catalog, new URLSearchParams({ group: id })) : industry, id)} />}
  </div>
}

function GroupComparison({ catalog, snapshot, layer, industry, onDrill }: {
  catalog: PeerCatalog; snapshot: PeerPriceSnapshot; layer: string; industry: string; onDrill: (id: string) => void
}) {
  const [params, setParams] = useSearchParams()
  const { resolvedTheme } = useTheme()
  const requestedDays = params.get('days') ?? '20'
  const days = ['5', '20', '60'].includes(requestedDays) ? Number(requestedDays) : 20
  const windows = useMemo(() => [5, 20, 60].map(period => ({ period, groups: computePeerPerformance(catalog, snapshot, period) })), [catalog, snapshot])
  const all = windows.find(window => window.period === days)!.groups
  const definitions = peerLayerGroups(catalog, layer, industry)
  const ids = definitions.map(group => group.id)
  const groups = all.filter(group => ids.includes(group.id))
  const ranked = [...groups].sort((a, b) => (b.returnPct ?? -Infinity) - (a.returnPct ?? -Infinity) || a.name.localeCompare(b.name))
  const baseline = layer === 'businesses' && industry !== 'all' ? all.find(group => group.id === industry) : undefined
  const focus = params.get('focus')
  const dates = snapshot.dates.slice(-days - 1)
  const chartData = dates.map((time, index) => ({ time, ...Object.fromEntries(groups.map(group => [group.id, group.path?.[index]])), baseline: baseline?.path?.[index] }))
  const lines = useMemo<LineConfig[]>(() => {
    const styles = getComputedStyle(document.documentElement)
    const palette = ['--chart-blue', '--chart-orange', '--chart-green', '--chart-purple', '--chart-red']
    return [
      ...groups.filter(group => group.path).map(group => {
        const index = ids.indexOf(group.id)
        return { key: group.id, label: group.name, color: styles.getPropertyValue(palette[index % palette.length]).trim(), lineWidth: group.id === focus ? 4 : 2, lineStyle: Math.floor(index / palette.length) % 3 }
      }),
      ...(baseline?.path && !ids.includes(baseline.id) ? [{ key: 'baseline', label: `${baseline.name} 평균`, color: styles.getPropertyValue('--chart-gray').trim(), lineWidth: 3, lineStyle: 2 }] : []),
    ]
    // Canvas colours must follow the current theme.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, snapshot, layer, industry, days, focus, resolvedTheme])
  const update = (key: string, value: string) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); return next })
  const incomplete = groups.filter(group => group.returnPct === null)
  const title = layer === 'industries' ? '업종 간 비교' : '세부 사업군 간 비교'
  return <section aria-label={title} className="space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><h2 className="text-section font-semibold">{title}</h2><p className="text-caption text-muted-foreground">{groups.length}개 그룹 · {layer === 'industries' ? '업종을 선택하면 세부 사업군을 비교합니다.' : '사업군을 선택하면 구성 종목의 Peer 비교로 이동합니다.'}</p></div>
      <PeriodToggle value={String(days)} onChange={value => update('days', value)} options={[5, 20, 60].map(value => ({ value: String(value), label: `${value}거래일` }))} />
    </div>
    {layer === 'businesses' && <div className="max-w-sm"><label className="mb-1 block text-caption" htmlFor="comparison-industry">비교할 업종</label><Select value={industryGroupExists(catalog, industry) ? industry : '__unknown__'} onValueChange={value => setParams(previous => navigatePeerLayer(previous, 'businesses', value))}><SelectTrigger id="comparison-industry" className="w-full"><SelectValue /></SelectTrigger><SelectContent>
      <SelectItem value="all">전체 사업군</SelectItem>
      {!industryGroupExists(catalog, industry) && <SelectItem value="__unknown__" disabled>알 수 없는 업종</SelectItem>}
      {catalog.groups.filter(group => PEER_PRESETS.includes(group.id) || group.id === industry).map(group => <SelectItem key={group.id} value={group.id}>{group.name}</SelectItem>)}
    </SelectContent></Select></div>}
    <p className="text-caption text-muted-foreground">가격 {dates[0]} → {snapshot.asOf}. 그룹별 구성 종목을 기간 시작에 동일가중합니다. 공식 업종지수나 배당 포함 총수익이 아닙니다. 기업이 여러 그룹에 중복될 수 있습니다.</p>
    {baseline && <p role="status" className="text-sm">자동 비교 기준: {baseline.name} 평균. 상위 업종에 현재 사업군의 종목도 포함됩니다.{baseline.returnPct === null && ' 기준 그룹은 관측·연속성 조건 미충족으로 미평가입니다.'}</p>}
    {requestedDays !== String(days) && <p role="status">지원하지 않는 기간으로 20거래일을 표시합니다.</p>}
    {focus && !groups.some(group => group.id === focus) && <p role="status">강조할 그룹을 찾을 수 없습니다. 아래 범례에서 다시 선택해 주세요.</p>}
    {!groups.length ? <p role="status" className="border border-border p-6">{industryGroupExists(catalog, industry) ? '등록된 세부 사업군이 없습니다. 다른 업종이나 전체 사업군을 선택해 주세요.' : '업종을 찾을 수 없습니다. 비교할 업종을 다시 선택해 주세요.'}</p> : <>
      <div className="border border-border p-3">
        <h3 className="font-medium">{title} · 시작값 100</h3>
        {lines.length ? <MultiLineChart data={chartData} lines={lines} showLegend={false} showLastValues={false} showLineTooltip height={340} formatValue={formatNumber} /> : <p role="status" className="p-6">선택 기간에 비교할 수 있는 그룹 가격이 없습니다.</p>}
        <div aria-label="그룹 차트 강조" className="flex max-h-48 flex-wrap gap-2 overflow-y-auto py-2">
          <Button size="sm" variant={!focus ? 'secondary' : 'outline'} aria-pressed={!focus} onClick={() => update('focus', '')}>전체 그룹 강조 해제</Button>
          {groups.map(group => <Button key={group.id} size="sm" variant={focus === group.id ? 'secondary' : 'outline'} aria-pressed={focus === group.id} onClick={() => update('focus', focus === group.id ? '' : group.id)}><span aria-hidden="true" className="w-4 border-t-2" style={{ borderColor: lines.find(line => line.key === group.id)?.color, borderTopStyle: lines.find(line => line.key === group.id)?.lineStyle ? 'dashed' : 'solid' }} />{group.name}{!group.path && ' · 미평가'}</Button>)}
        </div>
      </div>
      <p className="text-caption text-muted-foreground md:hidden">표를 좌우로 밀면 모든 기간의 성과를 볼 수 있습니다.</p>
      <Table aria-label={`${title} 성과표`}><TableCaption>{days}일 가격변동률 순. 동률은 같은 순위이며 미평가 그룹은 순위를 매기지 않습니다.</TableCaption><TableHeader><TableRow><TableHead className="sticky left-0 z-10 min-w-48 bg-background">{layer === 'industries' ? '업종' : '사업군'}</TableHead><TableHead>순위 · {days}일</TableHead>{windows.map(window => <TableHead key={window.period} className="text-right">{window.period}일</TableHead>)}{baseline && <TableHead className="text-right">업종 대비 · {days}일</TableHead>}<TableHead>상승 / 전체</TableHead><TableHead>관측 / 전체</TableHead></TableRow></TableHeader><TableBody>
        {ranked.map(group => <TableRow key={group.id}><TableCell className="sticky left-0 z-10 min-w-48 bg-background"><Button variant="link" className="h-auto whitespace-nowrap p-0 text-left" onClick={() => onDrill(group.id)}>{group.name}</Button><p className="text-caption text-muted-foreground">{group.memberCount}개 기업{group.memberCount === 1 && ' · 단일 기업'}{group.returnPct === null && ' · 미평가'}</p></TableCell><TableCell>{group.returnPct === null ? '-' : 1 + groups.filter(other => other.returnPct !== null && other.returnPct > group.returnPct! + 1e-10).length}</TableCell>
          {windows.map(window => { const value = window.groups.find(item => item.id === group.id)?.returnPct ?? null; return <TableCell key={window.period} className={`text-right tabular-nums ${color(value)}`}>{formatPercent(value)}</TableCell> })}
          {baseline && <TableCell className="text-right tabular-nums">{formatPp(group.returnPct !== null && baseline.returnPct !== null ? group.returnPct - baseline.returnPct : null, 1)}</TableCell>}
          <TableCell>{group.risingCount === null ? '-' : `${group.risingCount} / ${group.memberCount}`}</TableCell><TableCell>{group.coveredCount} / {group.memberCount}</TableCell>
        </TableRow>)}
      </TableBody></Table>
    </>}
    {incomplete.length > 0 && <Collapsible className="border border-border p-3"><p role="status" className="text-caption text-muted-foreground">{days}일 비교 {groups.length}개 중 {incomplete.length}개 그룹 미평가. 누락·연속성 미확인 종목을 제외해 평균을 다시 계산하지 않습니다.</p><CollapsibleTrigger asChild><Button variant="ghost" size="sm">미평가 그룹 상세</Button></CollapsibleTrigger><CollapsibleContent><ul className="space-y-2 text-caption">{incomplete.map(group => <li key={group.id}>{group.name}: {group.missingCodes.length ? group.missingCodes.map(code => catalog.companies.find(company => company.code === code)?.name ?? code).join(', ') : '구성 종목 없음'}</li>)}</ul></CollapsibleContent></Collapsible>}
    <p className="text-caption text-muted-foreground">탐색용 가격 비교이며 자동 매매 신호가 아닙니다. 기업행사 조정은 미검증입니다. 현재 구성원으로 과거 구간을 비교하므로 당시 투자 가능 성과로 해석하지 않습니다.</p>
  </section>
}
function industryGroupExists(catalog: PeerCatalog, industry: string) { return industry === 'all' || catalog.groups.some(group => group.id === industry) }
