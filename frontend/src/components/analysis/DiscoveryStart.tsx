import { useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowUpRight, ChartCandlestick, ChevronDown, History, PenLine, Search, TrendingUp } from 'lucide-react'
import { useRecommendations } from '@/hooks/useDiscovery'
import { useAnalysisStrategies } from '@/hooks/useAnalysisStrategies'
import { useSessionDraft } from '@/hooks/useSessionDraft'
import { useRecentCompanySearches } from '@/hooks/useRecentCompanySearches'
import CompanySearchCombobox from '@/components/shared/CompanySearchCombobox'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { DISCOVERY_SCENARIOS, SCENARIO_GROUPS, scenarioGroup, type ScenarioGroup } from '@/components/analysis/discoveryScenarios'
import { STRUCTURE_PRESETS, type StructureParams } from '@/components/structure/ChartStructureCard'
import { Skeleton } from '@/components/ui/skeleton'
import { StrategyConditionEditor } from '@/components/analysis/StrategyConditionEditor'
import { conditionInputError, isPurposeDraft, type PurposeDraft } from '@/components/analysis/discoveryDraft'
import type { DiscoveryRecommendation } from '@/components/analysis/discoveryTypes'
import type { StrategySubmission } from '@/components/analysis/StrategyLibrary'
import type { Company } from '@/types'

function PurposeEditor({ item, busy, onStart }: { item: DiscoveryRecommendation; busy: boolean; onStart: (body: StrategySubmission) => Promise<void> }) {
  const catalog = useAnalysisStrategies()
  const initial: PurposeDraft = { conditions: item.spec.strategy_conditions ?? [], market: item.spec.market, minimumCap: String(item.spec.min_market_cap / 100_000_000), asOf: '' }
  const [draft, setDraft, stored] = useSessionDraft(`explorer:discovery:purpose:v1:${item.id}`, initial, isPurposeDraft)
  const definitions = catalog.data?.items ?? []
  const missing = draft.conditions.some(c => !definitions.some(d => d.id === c.strategy_id))
  const invalid = draft.conditions.map(condition => { const definition = definitions.find(d => d.id === condition.strategy_id); return definition ? conditionInputError(condition, definition) : null }).find(Boolean)
  const patch = (next: Partial<PurposeDraft>) => setDraft(previous => ({ ...previous, ...next }))
  async function submit() {
    if (busy || !draft.conditions.length || missing || invalid) return
    const conditions = draft.conditions.map(c => `${definitions.find(d => d.id === c.strategy_id)?.label} (${Object.entries(c.params).map(([key, value]) => `${definitions.find(d => d.id === c.strategy_id)?.parameters[key]?.label ?? key}: ${value}`).join(', ')}; 최근 ${c.within_days}거래일)`)
    await onStart({ question: `${item.name}에서 조정한 조건입니다. ${draft.market === 'all' ? '국내 전체 시장' : draft.market}, 시가총액 ${draft.minimumCap}억원 이상.\n${conditions.map(text => `- ${text}`).join('\n')}`,
      spec: { ...item.spec, market: draft.market, min_market_cap: Number(draft.minimumCap) * 100_000_000, as_of: draft.asOf || null, strategy_conditions: draft.conditions }, ...(draft.asOf ? { as_of: draft.asOf } : {}) })
  }
  return <form aria-label="선택한 목적의 검색 조건" onSubmit={event => { event.preventDefault(); void submit() }} className="space-y-4">
    <div className="space-y-1"><h3 className="font-medium">{item.purpose}</h3><p className="text-sm text-muted-foreground">{item.misses}</p><p className="text-caption text-muted-foreground">아래 조건을 모두 만족하는 후보를 찾습니다. 추가·제거하면 이 목적의 기본 조건도 달라집니다.</p></div>
    <fieldset disabled={busy} className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3"><legend className="sr-only">검색 대상과 시점</legend>
      <div className="space-y-1.5"><Label htmlFor="purpose-market">시장</Label><Select value={draft.market} onValueChange={value => patch({ market: value as PurposeDraft['market'] })} disabled={busy}><SelectTrigger id="purpose-market" className="min-h-11"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">국내 전체</SelectItem><SelectItem value="KOSPI">KOSPI</SelectItem><SelectItem value="KOSDAQ">KOSDAQ</SelectItem></SelectContent></Select></div>
      <div className="space-y-1.5"><Label htmlFor="purpose-cap">최소 시가총액 (억원)</Label><Input className="min-h-11" id="purpose-cap" type="number" required min={0} max={1_000_000_000} step="any" value={draft.minimumCap} onChange={event => patch({ minimumCap: event.target.value })} /></div>
      <div className="space-y-1.5"><Label htmlFor="purpose-date">시세 기준일 (선택)</Label><Input className="min-h-11" id="purpose-date" type="date" value={draft.asOf} onChange={event => patch({ asOf: event.target.value })} /></div>
    </fieldset>
    <p className="text-caption text-muted-foreground">기준일을 비우면 최신 보유 시세로 찾습니다. 검색 대상에는 스팩·우선주 등이 포함될 수 있습니다.</p>
    {catalog.isPending && <Skeleton className="h-32 w-full" aria-label="계산 조건 불러오는 중" />}
    {catalog.isError && <ErrorState message="계산 조건을 불러오지 못했습니다." onRetry={() => catalog.refetch()} />}
    {catalog.data && <>
      <div className="space-y-3" aria-label="선택한 조건">{draft.conditions.map((condition, index) => {
        const definition = definitions.find(d => d.id === condition.strategy_id)
        return definition ? <StrategyConditionEditor key={`${condition.strategy_id}-${index}`} definition={definition} condition={condition} busy={busy}
          onChange={next => patch({ conditions: draft.conditions.map((c, i) => i === index ? next : c) })} onRemove={() => patch({ conditions: draft.conditions.filter((_, i) => i !== index) })} /> : <p key={index} role="alert" className="text-sm text-destructive">저장한 조건을 더 이상 지원하지 않습니다. 기본 조건을 복원해 주세요.</p>
      })}</div>
      <div className="flex flex-wrap items-center gap-2"><Select value="" disabled={busy || draft.conditions.length >= 12} onValueChange={id => {
        const definition = definitions.find(d => d.id === id)
        if (definition) patch({ conditions: [...draft.conditions, { strategy_id: id, params: { ...definition.defaults }, within_days: 1 }] })
      }}><SelectTrigger aria-label="검색 조건 추가" className="w-full sm:w-72"><SelectValue placeholder={`조건 추가 · ${draft.conditions.length}/12개`} /></SelectTrigger><SelectContent>{definitions.filter(d => !draft.conditions.some(c => c.strategy_id === d.id)).map(d => <SelectItem key={d.id} value={d.id}>{d.label}{!d.available ? ' · 자료 필요' : ''}</SelectItem>)}</SelectContent></Select>
        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setDraft(initial)}>기본 조건 복원</Button>
      </div>
    </>}
    {invalid && <p role="alert" className="text-sm text-destructive">{invalid} 해당 조건의 ‘조건 수정’을 열어 확인해 주세요.</p>}
    {!draft.conditions.length && <p role="status" className="text-sm text-muted-foreground">조건을 하나 이상 추가해 주세요.</p>}
    <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-caption text-muted-foreground">{stored === false ? '이 브라우저에서 초안을 보존하지 못했습니다.' : '조건 초안은 이 탭에서 자동 보존됩니다.'}</p><Button type="submit" className="min-h-11" disabled={busy || !catalog.data || missing || !!invalid || !draft.conditions.length}><Search className="size-4" />{busy ? '검색 준비 중…' : '이 조건으로 후보 찾기'}</Button></div>
    <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" type="button" size="sm">자료와 탐색의 한계<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger><CollapsibleContent><ul className="list-disc space-y-1 pl-5 text-caption text-muted-foreground">{item.limitations.map(text => <li key={text}>{text}</li>)}</ul></CollapsibleContent></Collapsible>
  </form>
}

export function DiscoveryStart({ busy, onStart, onDraw }: {
  busy: boolean; onStart: (body: StrategySubmission) => Promise<void>; onDraw: (params: StructureParams) => void
}) {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const query = useRecommendations()
  const intent = params.get('intent') ?? ''
  const group = scenarioGroup(params.get('scenario'), intent)
  const scenarios = DISCOVERY_SCENARIOS.filter(item => group === 'all' || item.group === group)
  const item = query.data?.items.find(item => item.id === intent)
  const [company, setCompany] = useState<Pick<Company, 'corp_name' | 'stock_code'> | null>(null)
  const history = useRecentCompanySearches()
  const companyPicker = useRef<HTMLFieldSetElement>(null)
  const selectCompany = (selected: Pick<Company, 'corp_name' | 'stock_code'>) => {
    setCompany(selected)
    history.remember(selected)
  }
  const preset = STRUCTURE_PRESETS.find(preset => preset.id === params.get('draw_preset')) ?? STRUCTURE_PRESETS[0]
  const changeGroup = (value: ScenarioGroup) => setParams(previous => {
    const next = new URLSearchParams(previous)
    next.set('scenario', value)
    if (value !== 'all' && !DISCOVERY_SCENARIOS.some(item => item.id === intent && item.group === value)) next.delete('intent')
    return next
  }, { replace: true, preventScrollReset: true })
  return <div className="space-y-5">
    <Card className="overflow-hidden border-primary/25 bg-primary/5" aria-label="아는 종목 분석">
      <CardHeader className="space-y-3"><div className="flex items-center gap-3"><span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground"><ChartCandlestick className="size-6" aria-hidden="true" /></span><div className="space-y-1"><h2 className="text-section font-semibold">아는 종목 분석</h2><p className="text-sm text-muted-foreground">종목을 정했다면, 차트부터 살펴보세요.</p></div></div></CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-2">
        <fieldset ref={companyPicker} disabled={busy} className="flex min-w-0 flex-wrap items-end gap-3"><legend className="sr-only">분석할 종목 선택</legend>
          <div className="min-w-0 flex-1 basis-64 space-y-2"><p className="text-caption font-medium">분석할 국내 종목</p><CompanySearchCombobox value={company} onSelect={selectCompany} placeholder="종목 이름 또는 코드 검색" className="min-h-11 w-full bg-background" /></div>
          <Button variant="outline" className="min-h-11 bg-background" disabled={!company?.stock_code || busy} onClick={() => { if (company?.stock_code) navigate(`/analyze/${company.stock_code}/summary?scan=1`) }}>기술적 분석 열기<ArrowUpRight className="size-4" /></Button>
        </fieldset>
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-primary/15 bg-background/80 p-3">
          <div className="min-w-0 flex-1 basis-60 space-y-2"><Label htmlFor="discovery-draw-preset" className="flex items-center gap-2"><PenLine className="size-4 text-primary" aria-hidden="true" />차트에 구조 바로 그리기</Label><Select value={preset.id} disabled={busy} onValueChange={value => setParams(previous => { const next = new URLSearchParams(previous); next.set('draw_preset', value); return next }, { replace: true, preventScrollReset: true })}><SelectTrigger id="discovery-draw-preset" className="min-h-11 w-full bg-background"><SelectValue /></SelectTrigger><SelectContent>{STRUCTURE_PRESETS.map(preset => <SelectItem key={preset.id} value={preset.id}>{preset.label}</SelectItem>)}</SelectContent></Select><p className="text-caption text-muted-foreground">{preset.purpose}</p></div>
          <Button className="min-h-11" disabled={!company?.stock_code || busy} onClick={() => { if (company?.stock_code) onDraw({ code: company.stock_code, market: 'kr', ...preset.params }) }}><PenLine className="size-4" />구조 바로 그리기</Button>
        </div>
        <section aria-label="최근 종목 검색" className="min-w-0 space-y-2 border-t border-primary/15 pt-3 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <h3 className="flex items-center gap-1.5 text-caption font-medium"><History className="size-3.5 text-muted-foreground" aria-hidden="true" />최근 검색</h3>
            {history.recent.length > 0 && <Button variant="ghost" size="sm" disabled={busy} aria-label="최근 종목 검색 기록 전체 삭제" className="min-h-11 text-caption text-muted-foreground" onClick={() => { history.clear(); companyPicker.current?.querySelector<HTMLButtonElement>('[role="combobox"]')?.focus() }}>전체 삭제</Button>}
          </div>
          {history.recent.length > 0 ? <ul className="flex min-w-0 flex-wrap gap-2" aria-label="최근 검색한 종목">
            {history.recent.map(recent => <li key={recent.stock_code} className="min-w-0 max-w-full"><Button variant="outline" disabled={busy} aria-pressed={company?.stock_code === recent.stock_code} aria-label={`${recent.corp_name} (${recent.stock_code}) 다시 선택`} title={`${recent.corp_name} (${recent.stock_code})`} className="min-h-11 max-w-full gap-2 bg-background aria-pressed:border-primary aria-pressed:bg-primary/5" onClick={() => selectCompany(recent)}><span className="truncate">{recent.corp_name}</span><span className="shrink-0 text-caption font-normal tabular-nums text-muted-foreground">{recent.stock_code}</span></Button></li>)}
          </ul> : <p className="text-caption text-muted-foreground">검색해 선택한 종목이 여기에 표시됩니다.</p>}
          {!history.stored ? <p role="status" className="text-caption text-muted-foreground">브라우저에 기록을 저장하지 못했습니다. 변경한 기록은 현재 화면에서만 유지됩니다.</p> : history.recent.length > 0 && <p className="text-caption text-muted-foreground">이 브라우저에 최근 8개까지 저장됩니다. 종목을 선택해 분석이나 구조 그리기를 이어가세요.</p>}
        </section>
      </CardContent>
    </Card>
    <Card aria-label="상황별 후보 찾기"><CardHeader className="space-y-3"><div className="flex flex-wrap items-center gap-2"><TrendingUp className="size-5 text-primary" aria-hidden="true" /><h2 className="text-section font-semibold">{group === 'rising' ? '상승 후보를 찾아보세요' : group === 'recovery' ? '반등과 전환의 움직임을 찾아보세요' : '어떤 상황을 찾나요?'}</h2>{group === 'rising' && <Badge variant="secondary">기본 탐색</Badge>}</div><p className="text-sm text-muted-foreground">{group === 'rising' ? '신고가·돌파·추세 지속·눌림 중 찾고 싶은 상승 흐름을 골라보세요.' : '상황을 고른 뒤 검색 대상과 계산 조건을 조정하세요.'}</p>
      <ToggleGroup type="single" value={group} onValueChange={value => { if (value) changeGroup(value as ScenarioGroup) }} variant="outline" aria-label="시나리오 범위" className="max-w-full flex-wrap justify-start">{SCENARIO_GROUPS.map(option => <ToggleGroupItem key={option.id} value={option.id} disabled={busy} className="min-h-11 px-3">{option.label}</ToggleGroupItem>)}</ToggleGroup>
    </CardHeader><CardContent className="space-y-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="발견 목적">{scenarios.map(purpose => <Button key={purpose.id} variant="outline" disabled={busy} aria-pressed={intent === purpose.id} className={`h-auto min-h-32 min-w-0 flex-col items-start justify-start gap-2 whitespace-normal p-4 text-left ${intent === purpose.id ? 'border-primary bg-primary/5 ring-1 ring-primary' : ''}`} onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.set('intent', purpose.id); return next }, { replace: true, preventScrollReset: true })}><span className="text-caption font-normal text-primary">{purpose.tag}</span><span className="break-keep text-sm font-semibold">{purpose.name}</span><span className="text-caption font-normal text-muted-foreground">{purpose.description}</span></Button>)}</div>
      {intent && !['natural', 'known'].includes(intent) && <div className="border-t pt-5">
        {query.isPending && <Skeleton className="h-32 w-full" aria-label="목적별 조건 불러오는 중" />}
        {query.isError && <ErrorState message="목적별 조건을 불러오지 못했습니다. 직접 조건을 설명해 검색할 수도 있습니다." onRetry={() => query.refetch()} />}
        {item && <PurposeEditor key={item.id} item={item} busy={busy} onStart={onStart} />}
        {query.data && !item && <p className="text-sm text-muted-foreground">이 목적의 조건이 없습니다. 다른 목적을 선택하거나 직접 조건을 설명해 주세요.</p>}
      </div>}
    </CardContent></Card>
  </div>
}
