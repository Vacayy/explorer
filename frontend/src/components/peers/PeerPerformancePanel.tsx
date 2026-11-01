import { PeerRelativeCandidates } from '@/components/peers/PeerRelativeCandidates'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTheme } from 'next-themes'
import { computePeerPerformance, groupOverlap, normalizedPeerPath } from '@/lib/peerPerformance'
import PeriodToggle from '@/components/shared/PeriodToggle'
import MultiLineChart from '@/components/charts/MultiLineChart'
import { Button } from '@/components/ui/button'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableCaption } from '@/components/ui/table'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { formatPercent, formatPp, formatNumber } from '@/utils/format'
import type { PeerCatalog, PeerPriceSnapshot } from '@/types/peer'

const changeColor = (value: number | null) => value === null ? 'text-muted-foreground' : value > 0 ? 'text-up' : value < 0 ? 'text-down' : ''

export function PeerPerformancePanel({ catalog, snapshot }: { catalog: PeerCatalog; snapshot: PeerPriceSnapshot }) {
  const [params, setParams] = useSearchParams()
  const { resolvedTheme } = useTheme()
  const requestedDays = params.get('days') ?? '20'
  const days = ['5', '20', '60'].includes(requestedDays) ? Number(requestedDays) : 20
  const groupId = params.get('group') ?? ''
  const baselineId = params.get('benchmark') ?? 'semiconductor_value_chain'
  const requestedStock = params.get('stock')
  const scope = params.get('scope') ?? 'all'
  const overview = params.get('overview') ?? 'groups'
  const groups = useMemo(() => computePeerPerformance(catalog, snapshot, days), [catalog, snapshot, days])
  const group = groups.find(item => item.id === groupId)
  const baseline = groups.find(item => item.id === baselineId)
  const member = requestedStock ? group?.members.find(item => item.code === requestedStock) : group?.members[0]
  const ranked = groups.filter(item => scope === 'all' || item.scope === scope)
    .sort((a, b) => (b.returnPct ?? -Infinity) - (a.returnPct ?? -Infinity) || a.name.localeCompare(b.name))
  const update = (key: string, value: string) => setParams(previous => {
    const next = new URLSearchParams(previous)
    if (value) next.set(key, value); else next.delete(key)
    if (key === 'group') next.delete('stock')
    return next
  })
  const dates = snapshot.dates.slice(-days - 1)
  const stockPath = member ? normalizedPeerPath(snapshot, member.code, days) : null
  const chartData = dates.map((time, index) => ({ time, group: group?.path?.[index], baseline: baseline?.path?.[index], stock: stockPath?.[index] }))
  const lines = useMemo(() => {
    const styles = getComputedStyle(document.documentElement)
    const color = (name: string) => styles.getPropertyValue(name).trim()
    return [
      ...(group?.path ? [{ key: 'group', label: group.name, color: color('--chart-blue'), lineWidth: 3 }] : []),
      ...(baseline?.path && baseline.id !== groupId ? [{ key: 'baseline', label: `기준 · ${baseline.name}`, color: color('--chart-gray'), lineStyle: 2 }] : []),
      ...(member && stockPath ? [{ key: 'stock', label: member.name, color: color('--chart-orange') }] : []),
    ]
    // The theme dependency resolves semantic CSS tokens for the canvas chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group, baseline, groupId, member, stockPath, resolvedTheme])
  const setResearch = () => update('view', 'research')
  return <div className="space-y-4">
    <div className="border border-border bg-muted/30 p-4 text-sm" role="note">
      <strong>탐색용 가격 비교 · 자동 신호 발행 안 함</strong>
      <p className="mt-1 text-muted-foreground">Naver 명시 정규장 종가 기준입니다. 기업행사 조정은 미검증이며 배당 포함 총수익이 아닙니다. 현재 그룹으로 과거 구간을 비교하므로 당시의 투자 가능 성과나 검증된 전략으로 해석하지 않습니다.</p>
    </div>
    <div className="flex flex-wrap items-end gap-3">
      <div><span className="mb-1 block text-caption">비교 기간</span><PeriodToggle value={String(days)} onChange={value => update('days', value)} options={[5, 20, 60].map(value => ({ value: String(value), label: `${value}거래일` }))} /></div>
      <div className="min-w-48 flex-1"><label htmlFor="peer-benchmark" className="mb-1 block text-caption">비교 기준 그룹</label>
        <Select value={baseline ? baselineId : '__unknown__'} onValueChange={value => update('benchmark', value)}><SelectTrigger id="peer-benchmark" className="w-full"><SelectValue /></SelectTrigger><SelectContent>
          {!baseline && <SelectItem value="__unknown__" disabled>존재하지 않는 기준 그룹</SelectItem>}
          {catalog.groups.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
        </SelectContent></Select>
      </div>
      <div className="min-w-48 flex-1"><label htmlFor="performance-group" className="mb-1 block text-caption">상세 비교 그룹</label>
        <Select value={groupId && !group ? '__unknown__' : groupId || '__all__'} onValueChange={value => update('group', value === '__all__' ? '' : value)}><SelectTrigger id="performance-group" className="w-full"><SelectValue /></SelectTrigger><SelectContent>
          {groupId && !group && <SelectItem value="__unknown__" disabled>존재하지 않는 그룹</SelectItem>}
          <SelectItem value="__all__">그룹 간 비교</SelectItem>
          {catalog.groups.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
        </SelectContent></Select>
      </div>
    </div>
    <p className="text-caption text-muted-foreground">가격 {dates[0]} → {snapshot.asOf} · 조사 {catalog.asOf} · {catalog.companies.length}기업·{catalog.groups.length}분류 · 게시된 정규장 스냅샷. 기간 시작 동일가중 · 기준 그룹은 시장 지수가 아닙니다.</p>
    {requestedDays !== String(days) && <p role="status" className="text-caption text-muted-foreground">지원하지 않는 기간으로 20거래일을 표시합니다.</p>}
    {!baseline && <p role="status" className="text-sm text-muted-foreground">기준 그룹을 찾을 수 없어 기준 대비 차이를 계산하지 않습니다. 비교 기준을 다시 선택해 주세요.</p>}
    {params.get('q') && <p className="text-caption text-muted-foreground">사업근거 검색어는 이 화면의 비교 구성원을 바꾸지 않습니다.</p>}
    {groupId && !group ? <div role="status" className="border border-border p-6">그룹을 찾을 수 없습니다. 상세 비교 그룹을 다시 선택해 주세요.</div> : group ? <>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border pb-3">
        <div><h2 className="text-section font-semibold">{group.name}</h2><p className="mt-1 text-caption text-muted-foreground">{catalog.groups.find(item => item.id === group.id)?.interpretation}</p></div>
        <Button variant="outline" onClick={setResearch}>사업 근거 보기</Button>
      </div>
      <div className="grid grid-cols-2 divide-x divide-border border border-border md:grid-cols-4">
        <div className="p-3"><p className="text-caption text-muted-foreground">그룹 가격변동률</p><p className={`text-xl font-semibold ${changeColor(group.returnPct)}`}>{formatPercent(group.returnPct)}</p></div>
        <div className="p-3"><p className="text-caption text-muted-foreground">기준 그룹 대비</p><p className="text-xl font-semibold">{formatPp(group.returnPct !== null && baseline?.returnPct != null ? group.returnPct - baseline.returnPct : null, 1)}</p></div>
        <div className="p-3"><p className="text-caption text-muted-foreground">상승 기업</p><p className="text-xl font-semibold">{group.risingCount === null ? '-' : `${group.risingCount} / ${group.memberCount}`}</p></div>
        <div className="p-3"><p className="text-caption text-muted-foreground">기준과 중복 기업</p><p className="text-xl font-semibold">{baseline ? groupOverlap(catalog, group.id, baseline.id) : '-'}</p></div>
      </div>
      {group.missingCodes.length > 0 && <p role="status" className="text-sm text-muted-foreground">전체 {group.memberCount}개 중 {group.coveredCount}개만 가격 관측·연속성 확인 조건을 충족합니다. 누락 종목을 제외해 기준선을 재계산하지 않습니다. 미평가: {group.missingCodes.join(', ')}</p>}
      <div className="border border-border p-3">
        <div className="flex flex-wrap items-end justify-between gap-3"><h3 className="font-medium">시작값 100 비교</h3>
          <div><label htmlFor="peer-chart-stock" className="mb-1 block text-caption">함께 볼 종목</label><Select value={member?.code ?? '__unknown__'} onValueChange={value => update('stock', value)}><SelectTrigger id="peer-chart-stock"><SelectValue /></SelectTrigger><SelectContent>
            {!member && <SelectItem value="__unknown__" disabled>그룹에 없는 종목</SelectItem>}
            {group.members.map(item => <SelectItem key={item.code} value={item.code}>{item.name}</SelectItem>)}
          </SelectContent></Select></div>
        </div>
        {requestedStock && !member && <p role="status" className="text-caption text-muted-foreground">선택한 종목이 이 그룹에 없습니다. 함께 볼 종목을 다시 선택해 주세요.</p>}
        {lines.length ? <MultiLineChart data={chartData} lines={lines} height={300} formatValue={formatNumber} /> : <p className="p-6 text-sm text-muted-foreground">차트를 그릴 충분한 가격 관측이 없습니다.</p>}
        <p className="text-caption text-muted-foreground">기본 선택 종목은 기간 가격변동률 1위입니다. 그룹 변경 시 다시 선택되며, 차트 선은 투자 추천을 의미하지 않습니다.</p>
      </div>
      <Table><TableCaption>자신을 제외한 Peer 평균과 비교합니다. 기업행사 조정 미검증 · 관측 순위이며 매매 신호가 아닙니다.</TableCaption><TableHeader><TableRow><TableHead>종목</TableHead><TableHead className="text-right">가격변동률</TableHead><TableHead className="text-right">Peer 대비</TableHead><TableHead className="text-right">순위</TableHead><TableHead>차트</TableHead></TableRow></TableHeader><TableBody>
        {group.members.map(item => <TableRow key={item.code}><TableCell><Link to={`/analyze/${item.code}/summary`} className="font-medium hover:underline">{item.name}</Link><span className="block text-caption text-muted-foreground">{item.code}</span></TableCell><TableCell className={`text-right tabular-nums ${changeColor(item.returnPct)}`}>{formatPercent(item.returnPct)}</TableCell><TableCell className={`text-right tabular-nums ${changeColor(item.excessPp)}`}>{formatPp(item.excessPp, 1)}</TableCell><TableCell className="text-right tabular-nums">{item.rank === null ? '-' : `${item.rank} / ${group.memberCount}`}</TableCell><TableCell><Button variant="ghost" size="sm" aria-pressed={member?.code === item.code} onClick={() => update('stock', item.code)} aria-label={`${item.name} 차트 비교`}>비교</Button></TableCell></TableRow>)}
      </TableBody></Table>
      {group.memberCount < 2 && <p className="text-caption text-muted-foreground">구성 기업이 1개여서 Peer 대비 성과를 계산하지 않습니다.</p>}
    </> : <>
      <PeriodToggle value={overview} onChange={value => update('overview', value)} options={[{ value: 'groups', label: '그룹 간 비교' }, { value: 'candidates', label: '상대 강약 종목' }]} />
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-section font-semibold">{overview === 'candidates' ? '상대성과로 종목 발견' : '그룹 간 비교'}</h2><PeriodToggle value={scope} onChange={value => update('scope', value)} options={[{ value: 'all', label: '전체' }, { value: 'product', label: '제품·공정' }, { value: 'value_chain', label: '밸류체인' }]} /></div>
      {ranked.length === 0 && <p role="status">해당 분류 범위를 찾을 수 없습니다. 전체를 선택해 주세요.</p>}
      {overview === 'candidates' ? <PeerRelativeCandidates groups={ranked} /> : <Table><TableCaption>서로 겹치는 그룹을 포함합니다. 1개 기업 그룹은 별도 표시하며 독립된 업종 지수로 해석하지 않습니다.</TableCaption><TableHeader><TableRow><TableHead>그룹</TableHead><TableHead className="text-right">가격변동률 ↓</TableHead><TableHead className="text-right">기준 대비</TableHead><TableHead className="text-right">중앙값</TableHead><TableHead className="text-right">상승 / 전체</TableHead><TableHead className="text-right">기준과 중복</TableHead></TableRow></TableHeader><TableBody>
        {ranked.map(item => <TableRow key={item.id}><TableCell><Button variant="link" className="h-auto whitespace-normal p-0 text-left" onClick={() => update('group', item.id)}>{item.name}</Button><span className="block text-caption text-muted-foreground">{item.scope === 'product' ? '제품·공정' : '밸류체인'}{item.memberCount === 1 ? ' · 단일 기업' : ''}{item.missingCodes.length ? ` · 관측 ${item.coveredCount}/${item.memberCount}` : ''}</span></TableCell><TableCell className={`text-right tabular-nums ${changeColor(item.returnPct)}`}>{formatPercent(item.returnPct)}</TableCell><TableCell className="text-right tabular-nums">{formatPp(item.returnPct !== null && baseline?.returnPct != null ? item.returnPct - baseline.returnPct : null, 1)}</TableCell><TableCell className="text-right tabular-nums">{formatPercent(item.medianPct)}</TableCell><TableCell className="text-right tabular-nums">{item.risingCount === null ? '-' : `${item.risingCount}/${item.memberCount}`}</TableCell><TableCell className="text-right tabular-nums">{baseline ? groupOverlap(catalog, item.id, baseline.id) : '-'}</TableCell></TableRow>)}
      </TableBody></Table>}
    </>}
    {snapshot.qualityIssues.filter(issue => issue.date > dates[0] && (!group || group.members.some(item => item.code === issue.code))).map(issue => <p key={`${issue.code}-${issue.date}`} role="status" className="border border-border bg-muted/30 p-3 text-caption text-muted-foreground">
      {catalog.companies.find(item => item.code === issue.code)?.name ?? issue.code} · {issue.date}: {issue.reason} 이 날짜를 가로지르는 종목 수익률 및 해당 그룹 기준선은 미평가합니다. <a className="text-primary underline" href={issue.sourceUrl} target="_blank" rel="noopener noreferrer">근거 (새 창)</a>
    </p>)}
    <Collapsible className="border-t border-border pt-3"><CollapsibleTrigger asChild><Button variant="ghost">가격 출처와 검증 범위</Button></CollapsibleTrigger><CollapsibleContent className="space-y-2 pt-3 text-caption text-muted-foreground">
      <p>수집 {snapshot.collectedAt} · 가격 버전 {snapshot.version} · 그룹 버전 {catalog.version}</p>
      <a className="text-primary underline" href={snapshot.sourceUrl.replace('{code}', member?.code ?? '005930')} target="_blank" rel="noopener noreferrer">Naver 정규장 일별 원천 응답 (새 창)</a>
      <ul className="list-disc pl-4">{snapshot.caveats.map((item, index) => <li key={index}>{item}</li>)}</ul>
      <p className="break-all">원천 내용 지문: {snapshot.sourceHash}</p>
    </CollapsibleContent></Collapsible>
  </div>
}
