import { PEER_PRESETS, peerBaseline, peerChildren, selectPeerPreset } from '@/lib/peerPresets'
import { PeerRelativeCandidates } from '@/components/peers/PeerRelativeCandidates'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTheme } from 'next-themes'
import { computePeerPerformance, groupOverlap, normalizedPeerPath } from '@/lib/peerPerformance'
import PeriodToggle from '@/components/shared/PeriodToggle'
import MultiLineChart, { type LineConfig } from '@/components/charts/MultiLineChart'
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
  const groupId = params.get('group') ?? (params.has('overview') ? '' : 'power_infrastructure')
  const automatic = peerBaseline(catalog, groupId)
  const baselineId = params.get('benchmark') ?? automatic.id
  const requestedStock = params.get('stock')
  const scope = params.get('scope') ?? 'all'
  const overview = params.get('overview') ?? 'groups'
  const groups = useMemo(() => computePeerPerformance(catalog, snapshot, days), [catalog, snapshot, days])
  const group = groups.find(item => item.id === groupId)
  const baseline = groups.find(item => item.id === baselineId)
  const member = group?.members.find(item => item.code === requestedStock)
  const windows = useMemo(() => [5, 20, 60].map(period => ({ period, groups: computePeerPerformance(catalog, snapshot, period) })), [catalog, snapshot])
  const children = peerChildren(catalog, groupId)
  const ranked = groups.filter(item => scope === 'all' || item.scope === scope)
    .sort((a, b) => (b.returnPct ?? -Infinity) - (a.returnPct ?? -Infinity) || a.name.localeCompare(b.name))
  const update = (key: string, value: string) => setParams(previous => {
    if (key === 'group') return selectPeerPreset(previous, value)
    const next = new URLSearchParams(previous)
    if (value) next.set(key, value); else next.delete(key)
    if (key === 'group') next.delete('stock')
    return next
  })
  const dates = snapshot.dates.slice(-days - 1)
  const paths = useMemo(() => (group?.members ?? []).map(item => ({ ...item, path: normalizedPeerPath(snapshot, item.code, days) })).sort((a, b) => a.code.localeCompare(b.code)), [group, snapshot, days])
  const chartData = dates.map((time, index) => ({ time, group: group?.path?.[index], baseline: baseline?.path?.[index],
    ...Object.fromEntries(paths.map(item => [`stock_${item.code}`, item.path?.[index]])) }))
  const lines = useMemo<LineConfig[]>(() => {
    const styles = getComputedStyle(document.documentElement)
    const color = (name: string) => styles.getPropertyValue(name).trim()
    const palette = ['--chart-blue', '--chart-orange', '--chart-green', '--chart-purple', '--chart-red']
    return [
      ...paths.filter(item => item.path).map(item => {
        const index = paths.findIndex(value => value.code === item.code)
        return { key: `stock_${item.code}`, label: item.name, color: color(palette[index % palette.length]), lineWidth: requestedStock === item.code ? 4 : 1, lineStyle: index >= palette.length ? 2 : 0 }
      }),
      ...(group?.path ? [{ key: 'group', label: `${group.name} 평균`, color: color('--chart-gray'), lineWidth: 3 }] : []),
      ...(baseline?.path && baseline.id !== groupId ? [{ key: 'baseline', label: `기준 · ${baseline.name}`, color: color('--chart-gray'), lineStyle: 2, lineWidth: 2 }] : []),
    ]
    // CSS tokens must be resolved again when the canvas theme changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paths, group, baseline, groupId, requestedStock, resolvedTheme])
  const qualityGroups = Object.values(snapshot.qualityIssues
    .filter(issue => issue.date > dates[0] && (!group || group.members.some(item => item.code === issue.code) || baseline?.members.some(item => item.code === issue.code)))
    .reduce<Record<string, PeerPriceSnapshot['qualityIssues']>>((result, issue) => {
      const key = JSON.stringify([issue.code, issue.reason])
      ;(result[key] ??= []).push(issue)
      return result
    }, {}))
  const setResearch = () => setParams(previous => { const next = new URLSearchParams(previous); next.set('view', 'research'); if (groupId) next.set('group', groupId); return next })
  return <div className="space-y-4">
    {params.get('layer') !== 'peers' && <nav aria-label="그룹 프리셋" className="flex flex-wrap gap-2">
      {PEER_PRESETS.map(id => catalog.groups.find(item => item.id === id)).filter(item => item !== undefined).map(item => <Button key={item.id} variant={groupId === item.id ? 'secondary' : 'outline'} aria-pressed={groupId === item.id} onClick={() => update('group', item.id)}>{item.name}<span className="text-muted-foreground">{catalog.companies.filter(company => company.groupIds.includes(item.id)).length}</span></Button>)}
      <Button variant={!groupId ? 'secondary' : 'ghost'} aria-pressed={!groupId} onClick={() => update('group', '')}>전체 그룹 탐색</Button>
    </nav>}
    <div className="flex flex-wrap items-center justify-between gap-3">
      <PeriodToggle value={String(days)} onChange={value => update('days', value)} options={[5, 20, 60].map(value => ({ value: String(value), label: `${value}거래일` }))} />
      {group && <p className="text-caption text-muted-foreground">조사된 구성 종목 {group.memberCount}개 · 전체 비교</p>}
    </div>
    <Collapsible open={params.get('settings') === '1'} onOpenChange={open => update('settings', open ? '1' : '')}>
      <CollapsibleTrigger asChild><Button variant="outline">비교 설정</Button></CollapsibleTrigger>
      <CollapsibleContent className="space-y-3 border border-border p-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-48 flex-1"><label htmlFor="peer-benchmark" className="mb-1 block text-caption">비교 기준 그룹</label>
            <Select value={params.has('benchmark') ? baseline ? baselineId : '__unknown__' : '__auto__'} onValueChange={value => update('benchmark', value === '__auto__' ? '' : value)}><SelectTrigger id="peer-benchmark" className="w-full"><SelectValue /></SelectTrigger><SelectContent>
              <SelectItem value="__auto__">자동 기준</SelectItem>
              {params.has('benchmark') && !baseline && <SelectItem value="__unknown__" disabled>존재하지 않는 기준 그룹</SelectItem>}
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
          {group && <div className="min-w-48 flex-1"><label htmlFor="peer-chart-stock" className="mb-1 block text-caption">강조할 종목</label><Select value={requestedStock ? member?.code ?? '__unknown__' : '__all__'} onValueChange={value => update('stock', value === '__all__' ? '' : value)}><SelectTrigger id="peer-chart-stock"><SelectValue /></SelectTrigger><SelectContent>
            <SelectItem value="__all__">전체 종목</SelectItem>
            {requestedStock && !member && <SelectItem value="__unknown__" disabled>그룹에 없는 종목</SelectItem>}
            {group.members.map(item => <SelectItem key={item.code} value={item.code}>{item.name}</SelectItem>)}
          </SelectContent></Select></div>}
        </div>
        <Button variant="ghost" onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.delete('benchmark'); next.delete('stock'); return next })}>자동 비교로 돌아가기</Button>
      </CollapsibleContent>
    </Collapsible>
    {baseline && <p role="status" className="text-sm">비교 기준: {baseline.name} · {params.has('benchmark') ? '직접 선택' : automatic.reason}</p>}
    <p className="text-caption text-muted-foreground">가격 {dates[0]} → {snapshot.asOf} · 조사 {catalog.asOf} · {catalog.companies.length}기업·{catalog.groups.length}분류 · 게시된 정규장 스냅샷. 기간 시작 동일가중 · 기준 그룹은 시장 지수가 아닙니다.</p>
    {requestedDays !== String(days) && <p role="status" className="text-caption text-muted-foreground">지원하지 않는 기간으로 20거래일을 표시합니다.</p>}
    {baseline && baseline.id !== groupId && baseline.missingCodes.length > 0 && <p role="status" className="text-sm text-muted-foreground">비교 기준 {baseline.name}은 가격 관측·연속성 조건 미충족으로 미평가입니다. 기준선과 기준 대비 성과를 표시하지 않습니다. 미평가 구성 종목: {baseline.missingCodes.map(code => catalog.companies.find(company => company.code === code)?.name ?? code).join(', ')}</p>}
    {params.has('benchmark') && !baseline && <p role="status" className="text-sm text-muted-foreground">기준 그룹을 찾을 수 없어 기준 대비 차이를 계산하지 않습니다. 비교 기준을 다시 선택해 주세요.</p>}
    {params.get('q') && <p className="text-caption text-muted-foreground">사업근거 검색어는 이 화면의 비교 구성원을 바꾸지 않습니다.</p>}
    {groupId && !group ? <div role="status" className="border border-border p-6">그룹을 찾을 수 없습니다. 상세 비교 그룹을 다시 선택해 주세요.</div> : group ? <>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border pb-3">
        <div><h2 className="text-section font-semibold">{group.name}</h2><p className="mt-1 text-caption text-muted-foreground">{catalog.groups.find(item => item.id === group.id)?.interpretation}</p></div>
        <Button variant="outline" onClick={setResearch}>사업 근거 보기</Button>
      </div>
      <div className="grid grid-cols-2 divide-x divide-border border border-border md:grid-cols-4">
        {windows.map(({ period, groups: values }) => <div className="p-3" key={period}><p className="text-caption text-muted-foreground">그룹 {period}일 가격변동률</p><p className={`text-xl font-semibold ${changeColor(values.find(value => value.id === group.id)?.returnPct ?? null)}`}>{formatPercent(values.find(value => value.id === group.id)?.returnPct ?? null)}</p></div>)}
        <div className="p-3"><p className="text-caption text-muted-foreground">상승 기업 · {days}일</p><p className="text-xl font-semibold">{group.risingCount === null ? '-' : `${group.risingCount} / ${group.memberCount}`}</p></div>
      </div>
      {baseline && baseline.id !== group.id && <p className="text-caption text-muted-foreground">{days}일 기준 그룹 대비 {formatPp(group.returnPct !== null && baseline.returnPct !== null ? group.returnPct - baseline.returnPct : null, 1)} · 중복 기업 {groupOverlap(catalog, group.id, baseline.id)}개. 상위 그룹에는 현재 그룹 종목도 포함됩니다.</p>}
      {group.missingCodes.length > 0 && <p role="status" className="text-sm text-muted-foreground">전체 {group.memberCount}개 중 {group.coveredCount}개만 가격 관측·연속성 확인 조건을 충족합니다. 누락 종목을 제외해 기준선을 재계산하지 않습니다. 미평가: {group.missingCodes.join(', ')}</p>}
      <div className="border border-border p-3">
        <h3 className="font-medium">전체 구성 종목 · 시작값 100 비교</h3>
        {requestedStock && !member && <p role="status" className="text-caption text-muted-foreground">선택한 종목이 이 그룹에 없습니다. 비교 설정에서 강조할 종목을 다시 선택해 주세요.</p>}
        {lines.length ? <MultiLineChart data={chartData} lines={lines} showLegend={false} showLastValues={false} showLineTooltip onLineClick={key => { if (key.startsWith('stock_')) { const code = key.slice(6); update('stock', requestedStock === code ? '' : code) } }} height={340} formatValue={formatNumber} /> : <p className="p-6 text-sm text-muted-foreground">차트를 그릴 충분한 가격 관측이 없습니다.</p>}
        <div aria-label="차트 종목 강조" className="flex max-h-48 flex-wrap gap-2 overflow-y-auto py-2">
          <Button variant={!requestedStock ? 'secondary' : 'outline'} size="sm" aria-pressed={!requestedStock} onClick={() => update('stock', '')}>전체 종목</Button>
          {paths.map(item => <Button key={item.code} size="sm" variant={requestedStock === item.code ? 'secondary' : 'outline'} aria-pressed={requestedStock === item.code} onClick={() => update('stock', requestedStock === item.code ? '' : item.code)}>
            <span aria-hidden="true" className="w-4 border-t-2" style={{ borderColor: lines.find(line => line.key === `stock_${item.code}`)?.color, borderTopStyle: lines.find(line => line.key === `stock_${item.code}`)?.lineStyle === 2 ? 'dashed' : 'solid' }} />{item.name}{!item.path && ' · 미평가'}
          </Button>)}
        </div>
        <p className="text-caption text-muted-foreground">{group.path ? '회색 굵은 선: 그룹 평균. ' : ''}{baseline?.path && baseline.id !== group.id ? '회색 점선: 비교 기준. ' : ''}종목 버튼을 누르면 해당 선을 굵게 표시합니다. 모든 선은 선택 기간 시작값 100이며 투자 추천이 아닙니다.</p>
      </div>
      <p className="text-caption text-muted-foreground md:hidden">표를 좌우로 밀면 모든 기간과 Peer 대비 성과를 볼 수 있습니다.</p>
      <Table aria-label="구성 종목 성과"><TableCaption>기간별 가격변동률과 {days}일 자기 제외 Peer 대비. {days}일 가격변동률 순이며 매매 신호가 아닙니다.</TableCaption><TableHeader><TableRow><TableHead className="sticky left-0 z-10 min-w-36 bg-background">종목</TableHead>{windows.map(({ period }) => <TableHead key={period} className="text-right">{period}일</TableHead>)}<TableHead className="text-right">Peer 대비 · {days}일</TableHead><TableHead className="text-right">순위</TableHead><TableHead>차트</TableHead></TableRow></TableHeader><TableBody>
        {group.members.map(item => <TableRow key={item.code}><TableCell className="sticky left-0 z-10 min-w-36 bg-background"><Link to={`/analyze/${item.code}/summary`} className="font-medium hover:underline">{item.name}</Link><span className="block text-caption text-muted-foreground">{item.code}</span></TableCell>
          {windows.map(({ period, groups: values }) => { const value = values.find(value => value.id === group.id)?.members.find(value => value.code === item.code)?.returnPct ?? null; return <TableCell key={period} className={`text-right tabular-nums ${changeColor(value)}`}>{formatPercent(value)}</TableCell> })}
          <TableCell className={`text-right tabular-nums ${changeColor(item.excessPp)}`}>{formatPp(item.excessPp, 1)}</TableCell><TableCell className="text-right tabular-nums">{item.rank === null ? '-' : `${item.rank} / ${group.memberCount}`}</TableCell><TableCell><Button variant="ghost" size="sm" aria-pressed={member?.code === item.code} onClick={() => update('stock', item.code)} aria-label={`${item.name} 차트 강조`}>강조</Button></TableCell></TableRow>)}
      </TableBody></Table>
      {children.length > 0 && <section aria-label="세부 사업군 비교" className="space-y-2">
        <h3 className="font-medium">세부 사업군 비교</h3>
        <p className="text-caption text-muted-foreground">같은 기업이 여러 사업군에 포함될 수 있습니다. 합산 비중이나 독립된 포트폴리오가 아닙니다.</p>
        <Table><TableHeader><TableRow><TableHead>사업군</TableHead><TableHead>구성 기업</TableHead>{windows.map(({ period }) => <TableHead key={period} className="text-right">{period}일</TableHead>)}</TableRow></TableHeader><TableBody>
          {children.map(child => <TableRow key={child.id}><TableCell><Button variant="link" className="h-auto min-w-40 whitespace-nowrap p-0 text-left" onClick={() => update('group', child.id)}>{child.name}</Button></TableCell><TableCell>{catalog.companies.filter(company => company.groupIds.includes(child.id)).length}개</TableCell>{windows.map(({ period, groups: values }) => { const value = values.find(value => value.id === child.id)?.returnPct ?? null; return <TableCell key={period} className={`text-right tabular-nums ${changeColor(value)}`}>{formatPercent(value)}</TableCell> })}</TableRow>)}
        </TableBody></Table>
      </section>}
      {group.memberCount < 2 && <p className="text-caption text-muted-foreground">구성 기업이 1개여서 Peer 대비 성과를 계산하지 않습니다.</p>}
    </> : <>
      <PeriodToggle value={overview} onChange={value => update('overview', value)} options={[{ value: 'groups', label: '그룹 간 비교' }, { value: 'candidates', label: '상대 강약 종목' }]} />
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-section font-semibold">{overview === 'candidates' ? '상대성과로 종목 발견' : '그룹 간 비교'}</h2><PeriodToggle value={scope} onChange={value => update('scope', value)} options={[{ value: 'all', label: '전체' }, { value: 'product', label: '제품·공정' }, { value: 'value_chain', label: '밸류체인' }]} /></div>
      {ranked.length === 0 && <p role="status">해당 분류 범위를 찾을 수 없습니다. 전체를 선택해 주세요.</p>}
      {overview === 'candidates' ? <PeerRelativeCandidates groups={ranked} /> : <Table><TableCaption>서로 겹치는 그룹을 포함합니다. 1개 기업 그룹은 별도 표시하며 독립된 업종 지수로 해석하지 않습니다.</TableCaption><TableHeader><TableRow><TableHead>그룹</TableHead><TableHead className="text-right">가격변동률 ↓</TableHead><TableHead className="text-right">기준 대비</TableHead><TableHead className="text-right">중앙값</TableHead><TableHead className="text-right">상승 / 전체</TableHead><TableHead className="text-right">기준과 중복</TableHead></TableRow></TableHeader><TableBody>
        {ranked.map(item => <TableRow key={item.id}><TableCell><Button variant="link" className="h-auto min-w-40 whitespace-nowrap p-0 text-left" onClick={() => update('group', item.id)}>{item.name}</Button><span className="block text-caption text-muted-foreground">{item.scope === 'product' ? '제품·공정' : '밸류체인'}{item.memberCount === 1 ? ' · 단일 기업' : ''}{item.missingCodes.length ? ` · 관측 ${item.coveredCount}/${item.memberCount}` : ''}</span></TableCell><TableCell className={`text-right tabular-nums ${changeColor(item.returnPct)}`}>{formatPercent(item.returnPct)}</TableCell><TableCell className="text-right tabular-nums">{formatPp(item.returnPct !== null && baseline?.returnPct != null ? item.returnPct - baseline.returnPct : null, 1)}</TableCell><TableCell className="text-right tabular-nums">{formatPercent(item.medianPct)}</TableCell><TableCell className="text-right tabular-nums">{item.risingCount === null ? '-' : `${item.risingCount}/${item.memberCount}`}</TableCell><TableCell className="text-right tabular-nums">{baseline ? groupOverlap(catalog, item.id, baseline.id) : '-'}</TableCell></TableRow>)}
      </TableBody></Table>}
    </>}
    <div className="border border-border bg-muted/30 p-4 text-sm" role="note">
      <strong>탐색용 가격 비교 · 자동 신호 발행 안 함</strong>
      <p className="mt-1 text-muted-foreground">Naver 명시 정규장 종가 기준입니다. 기업행사 조정은 미검증이며 배당 포함 총수익이 아닙니다. 현재 그룹으로 과거 구간을 비교하므로 당시의 투자 가능 성과나 검증된 전략으로 해석하지 않습니다.</p>
    </div>
    {qualityGroups.map(issues => <Collapsible key={JSON.stringify([issues[0].code, issues[0].reason])} className="border border-border bg-muted/30 p-3 text-caption text-muted-foreground">
      <p role="status">{catalog.companies.find(item => item.code === issues[0].code)?.name ?? issues[0].code} · {issues[0].date}{issues.length > 1 && ` 외 ${issues.length - 1}일`}: {issues[0].reason} 이 날짜를 가로지르는 종목 수익률 및 해당 그룹 기준선은 미평가합니다.</p>
      <CollapsibleTrigger asChild><Button variant="ghost" size="sm">날짜별 근거 {issues.length}건</Button></CollapsibleTrigger>
      <CollapsibleContent><ul className="space-y-2 pt-2">{issues.map((issue, index) => <li key={`${issue.date}-${index}`}><a className="text-primary underline" href={issue.sourceUrl} target="_blank" rel="noopener noreferrer">{issue.date} 근거 (새 창)</a></li>)}</ul></CollapsibleContent>
    </Collapsible>)}
    <Collapsible className="border-t border-border pt-3"><CollapsibleTrigger asChild><Button variant="ghost">가격 출처와 검증 범위</Button></CollapsibleTrigger><CollapsibleContent className="space-y-2 pt-3 text-caption text-muted-foreground">
      <p>수집 {snapshot.collectedAt} · 가격 버전 {snapshot.version} · 그룹 버전 {catalog.version}</p>
      <a className="text-primary underline" href={snapshot.sourceUrl.replace('{code}', member?.code ?? '005930')} target="_blank" rel="noopener noreferrer">Naver 정규장 일별 원천 응답 (새 창)</a>
      <ul className="list-disc pl-4">{snapshot.caveats.map((item, index) => <li key={index}>{item}</li>)}</ul>
      <p className="break-all">원천 내용 지문: {snapshot.sourceHash}</p>
    </CollapsibleContent></Collapsible>
  </div>
}
