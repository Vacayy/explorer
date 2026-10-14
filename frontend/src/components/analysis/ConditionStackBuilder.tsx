import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Info, Layers, LoaderCircle, Plus, Search } from 'lucide-react'
import { toast } from 'sonner'
import { useAnalysisStrategies } from '@/hooks/useAnalysisStrategies'
import { useRecommendations } from '@/hooks/useDiscovery'
import { useSessionDraft } from '@/hooks/useSessionDraft'
import { ErrorState } from '@/components/shared/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { StrategyConditionEditor } from '@/components/analysis/StrategyConditionEditor'
import { DISCOVERY_SCENARIOS, SCENARIO_GROUPS, scenarioGroup, type ScenarioGroup } from '@/components/analysis/discoveryScenarios'
import { conditionInputError, isPurposeDraft, MAX_STACKED_CONDITIONS, stackConditions, type PurposeDraft } from '@/components/analysis/discoveryDraft'
import type { AnalysisSpec, StrategyCondition, StrategyDefinition } from '@/components/analysis/types'

export interface StrategySubmission {
  question: string
  spec: Partial<AnalysisSpec>
  as_of?: string
}

const CATEGORIES = ['시세동향', '지표신호', '가격 구조', '추세·모멘텀', '평균회귀', '순위종목'] as const
const DATA_LABELS: Record<string, string> = {
  daily_ohlcv: '일봉 시세', ohlcv: '시세와 거래량', intraday_10m: '10분봉 시세',
  ohlcv_10m: '10분봉 시세', trading_value: '실제 거래대금', shares: '상장주식 수',
  shares_outstanding: '상장주식 수', market_cap: '시가총액',
  open: '시가', high: '고가', low: '저가', close: '종가', volume: '거래량', timestamp: '10분봉 시각',
}
const EMPTY: PurposeDraft = { conditions: [], market: 'all', minimumCap: '0', asOf: '' }

function DefinitionInfo({ definition }: { definition: StrategyDefinition }) {
  return <Popover><PopoverTrigger asChild><Button type="button" variant="ghost" size="icon-sm" className="size-9 shrink-0 text-muted-foreground" aria-label={`${definition.label} 계산 기준 보기`}><Info className="size-3.5" /></Button></PopoverTrigger>
    <PopoverContent align="end" className="w-72 space-y-2 break-words text-caption text-muted-foreground">
      <p className="text-sm font-medium text-foreground">{definition.label}</p>
      <p>{definition.description}</p>
      <p><span className="font-medium text-foreground">계산 기준: </span>{definition.formula}</p>
      <p>필요 자료: {definition.required_data.map(item => DATA_LABELS[item] ?? item).join(' · ')}</p>
      {!definition.available && <p className="text-hypothesis">현재 필요한 자료가 없어 판정할 수 없습니다. 실행 결과에 미평가 사유를 표시합니다.</p>}
    </PopoverContent></Popover>
}

/** Presets and catalog conditions stack into one AND list (spec.strategy_conditions). */
export function ConditionStackBuilder({ busy, onStart }: { busy: boolean; onStart: (body: StrategySubmission) => Promise<void> }) {
  const [params, setParams] = useSearchParams()
  const catalog = useAnalysisStrategies()
  const presets = useRecommendations()
  const [draft, setDraft, stored] = useSessionDraft('explorer:discovery:stack:v1', EMPTY, isPurposeDraft)
  const [search, setSearch] = useState('')
  const group = scenarioGroup(params.get('scenario'), params.get('intent') ?? '')
  const scenarios = DISCOVERY_SCENARIOS.filter(item => group === 'all' || item.group === group)
  const definitions = catalog.data?.items ?? []
  const definitionOf = (id: string) => definitions.find(d => d.id === id)
  const stacked = new Set(draft.conditions.map(c => c.strategy_id))
  const full = draft.conditions.length >= MAX_STACKED_CONDITIONS
  const term = search.trim().toLocaleLowerCase()
  const visible = definitions.filter(d => `${d.label} ${d.description}`.toLocaleLowerCase().includes(term))
  const missing = draft.conditions.some(c => !definitionOf(c.strategy_id))
  const invalid = draft.conditions.map(c => { const definition = definitionOf(c.strategy_id); return definition ? conditionInputError(c, definition) : null }).find(Boolean)
  const patch = (next: Partial<PurposeDraft>) => setDraft(previous => ({ ...previous, ...next }))
  const changeGroup = (value: ScenarioGroup) => setParams(previous => { const next = new URLSearchParams(previous); next.set('scenario', value); next.delete('intent'); return next }, { replace: true, preventScrollReset: true })

  function add(incoming: StrategyCondition[]) {
    const result = stackConditions(draft.conditions, incoming)
    patch({ conditions: result.conditions })
    const notes = [result.duplicate && `이미 쌓인 조건 ${result.duplicate}개는 기존 설정을 유지했습니다.`, result.overflow && `최대 ${MAX_STACKED_CONDITIONS}개라 ${result.overflow}개는 추가하지 못했습니다.`].filter(Boolean)
    if (notes.length) toast(notes.join(' '))
  }
  const remove = (ids: string[]) => patch({ conditions: draft.conditions.filter(c => !ids.includes(c.strategy_id)) })
  const presetConditions = (id: string) => presets.data?.items.find(item => item.id === id)?.spec.strategy_conditions ?? []
  function togglePreset(id: string) {
    const conditions = presetConditions(id)
    if (conditions.length && conditions.every(c => stacked.has(c.strategy_id))) remove(conditions.map(c => c.strategy_id))
    else add(conditions)
  }
  function toggleDefinition(definition: StrategyDefinition) {
    if (stacked.has(definition.id)) remove([definition.id])
    else add([{ strategy_id: definition.id, params: { ...definition.defaults }, within_days: 1 }])
  }
  async function submit() {
    if (busy || !draft.conditions.length || missing || invalid) return
    const lines = draft.conditions.map(c => {
      const definition = definitionOf(c.strategy_id)!
      const settings = Object.entries(c.params).map(([key, value]) => `${definition.parameters[key]?.label ?? key}: ${String(value)}`)
      if (c.within_days > 1) settings.push(`최근 ${c.within_days}거래일`)
      return `- ${definition.label}${settings.length ? ` (${settings.join(', ')})` : ''}`
    })
    const cap = Number(draft.minimumCap)
    await onStart({ question: `${draft.market === 'all' ? '국내 전체 시장' : draft.market}${cap ? `, 시가총액 ${draft.minimumCap}억원 이상` : ''}에서 다음 조건을 모두 만족하는 종목을 찾아줘.\n${lines.join('\n')}`,
      spec: { mode: 'catalog', market: draft.market, min_market_cap: cap * 100_000_000, as_of: draft.asOf || null, pattern: 'none', require_52w: false, require_ma: false, strategy_conditions: draft.conditions },
      ...(draft.asOf ? { as_of: draft.asOf } : {}) })
  }

  return <Card aria-label="조건을 쌓아 종목 찾기">
    <CardHeader className="space-y-1"><div className="flex items-center gap-2"><Layers className="size-5 text-primary" aria-hidden="true" /><h2 className="text-section font-semibold">조건을 쌓아 종목 찾기</h2></div>
      <p className="text-sm text-muted-foreground">빠른 시작이나 조건 목록에서 블록을 더하세요. 쌓인 조건을 모두 만족하는 종목을 찾습니다.</p></CardHeader>
    <CardContent className="space-y-6">
      <section aria-label="빠른 시작" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">빠른 시작 <span className="font-normal text-muted-foreground">· 눌러서 조건 묶음을 쌓기</span></h3>
          <ToggleGroup type="single" value={group} onValueChange={value => { if (value) changeGroup(value as ScenarioGroup) }} variant="outline" size="sm" aria-label="빠른 시작 범위" className="max-w-full flex-wrap justify-start">{SCENARIO_GROUPS.map(option => <ToggleGroupItem key={option.id} value={option.id} disabled={busy} className="min-h-9 px-3">{option.label}</ToggleGroupItem>)}</ToggleGroup></div>
        {presets.isError && <ErrorState message="빠른 시작 조건을 불러오지 못했습니다. 아래 조건 목록에서 직접 쌓을 수 있습니다." onRetry={() => presets.refetch()} />}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">{scenarios.map(scenario => {
          const conditions = presetConditions(scenario.id)
          const applied = conditions.length > 0 && conditions.every(c => stacked.has(c.strategy_id))
          return <Button key={scenario.id} type="button" variant="outline" disabled={busy || !conditions.length} aria-pressed={applied}
            className={`h-auto min-h-20 min-w-0 items-start justify-between gap-3 whitespace-normal p-3 text-left ${applied ? 'border-primary bg-primary/5 ring-1 ring-primary' : ''}`} onClick={() => togglePreset(scenario.id)}>
            <span className="flex min-w-0 flex-col gap-1"><span className="text-caption font-normal text-primary">{scenario.tag} · 조건 {conditions.length || '–'}개</span><span className="break-keep text-sm font-semibold">{scenario.name}</span><span className="text-caption font-normal text-muted-foreground">{scenario.description}</span></span>
            {applied ? <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" /> : <Plus className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
          </Button>
        })}</div>
      </section>

      {catalog.isPending && <div role="status" aria-label="계산 조건 불러오는 중" className="grid gap-5 lg:grid-cols-[20rem_minmax(0,1fr)]"><Skeleton className="h-80 w-full" /><Skeleton className="h-80 w-full" /></div>}
      {catalog.isError && <ErrorState message="계산 조건을 불러오지 못했습니다." onRetry={() => catalog.refetch()} />}
      {catalog.data && <div className="grid min-w-0 grid-cols-1 items-start gap-5 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <section aria-label="조건 목록" className="order-2 min-w-0 space-y-3 rounded-xl border p-3 lg:order-1">
          <div className="relative"><Label htmlFor="stack-search" className="sr-only">조건 찾기</Label><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input id="stack-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="이평, 신고가, RSI…" className="min-h-10 pl-9" /></div>
          <p role="status" className="text-caption text-muted-foreground">전체 {definitions.length}개{term && ` · 검색 ${visible.length}개`} · 쌓은 조건 {draft.conditions.length}/{MAX_STACKED_CONDITIONS}</p>
          {!visible.length ? <div className="space-y-2 py-6 text-center"><p className="text-sm text-muted-foreground">검색어에 맞는 조건이 없습니다.</p><Button type="button" variant="outline" size="sm" onClick={() => setSearch('')}>검색 지우기</Button></div>
            : <ScrollArea className="h-[24rem] lg:h-[30rem]"><div className="space-y-4 pr-3">{CATEGORIES.map(category => {
              const items = visible.filter(d => d.category === category)
              return items.length > 0 && <div key={category} className="space-y-1"><h4 className="px-1 text-caption font-medium text-muted-foreground">{category} {items.length}</h4><ul>{items.map(definition => {
                const on = stacked.has(definition.id)
                return <li key={definition.id} className="flex items-center gap-1">
                  <Button type="button" variant="ghost" disabled={busy || (!on && full)} aria-pressed={on} className={`h-auto min-h-9 min-w-0 flex-1 justify-between gap-2 whitespace-normal px-2 py-1.5 text-left text-sm font-normal ${on ? 'bg-primary/5 text-primary' : ''}`} onClick={() => toggleDefinition(definition)}>
                    <span className="min-w-0 break-keep">{definition.label}{!definition.available && <Badge variant="secondary" className="ml-1.5 font-normal">자료 필요</Badge>}</span>
                    {on ? <Check className="size-4 shrink-0" aria-hidden="true" /> : <Plus className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
                  </Button>
                  <DefinitionInfo definition={definition} />
                </li>
              })}</ul></div>
            })}</div></ScrollArea>}
        </section>

        <form aria-label="쌓은 검색 조건" onSubmit={event => { event.preventDefault(); void submit() }} className="order-1 min-w-0 space-y-4 lg:order-2">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">내 조건 {draft.conditions.length}/{MAX_STACKED_CONDITIONS} <span className="font-normal text-muted-foreground">· 모두 만족</span></h3>
            {draft.conditions.length > 0 && <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => patch({ conditions: [] })}>모두 비우기</Button>}</div>
          {!draft.conditions.length ? <div className="rounded-xl border border-dashed p-8 text-center"><p className="text-sm font-medium">아직 쌓인 조건이 없습니다</p><p className="mt-1 text-caption text-muted-foreground">빠른 시작 카드를 누르거나 조건 목록의 +로 블록을 추가하세요.</p></div>
            : <ol className="space-y-0" aria-label="쌓은 조건 블록">{draft.conditions.map((condition, index) => {
              const definition = definitionOf(condition.strategy_id)
              return <li key={condition.strategy_id}>
                {index > 0 && <div className="flex items-center gap-2 py-1.5 pl-3 text-caption text-muted-foreground" aria-hidden="true"><span className="h-4 w-px bg-border" />그리고</div>}
                <div className="flex min-w-0 items-start gap-2"><span className="mt-3 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-caption font-medium tabular-nums text-primary">{index + 1}</span>
                  <div className="min-w-0 flex-1">{definition ? <StrategyConditionEditor definition={definition} condition={condition} busy={busy}
                    onChange={next => patch({ conditions: draft.conditions.map((c, i) => i === index ? next : c) })} onRemove={() => remove([condition.strategy_id])} />
                    : <div className="flex items-center justify-between gap-2 rounded-lg border p-3"><p role="alert" className="text-sm text-destructive">더 이상 지원하지 않는 조건입니다.</p><Button type="button" variant="ghost" size="sm" onClick={() => remove([condition.strategy_id])}>제거</Button></div>}</div></div>
              </li>
            })}</ol>}
          <fieldset disabled={busy} className="grid min-w-0 grid-cols-1 gap-3 border-t pt-4 sm:grid-cols-3"><legend className="sr-only">검색 대상과 시점</legend>
            <div className="space-y-1.5"><Label htmlFor="stack-market">시장</Label><Select value={draft.market} onValueChange={value => patch({ market: value as PurposeDraft['market'] })} disabled={busy}><SelectTrigger id="stack-market" className="min-h-11"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">국내 전체</SelectItem><SelectItem value="KOSPI">KOSPI</SelectItem><SelectItem value="KOSDAQ">KOSDAQ</SelectItem></SelectContent></Select></div>
            <div className="space-y-1.5"><Label htmlFor="stack-cap">최소 시가총액 (억원)</Label><Input className="min-h-11" id="stack-cap" type="number" required min={0} max={1_000_000_000} step="any" value={draft.minimumCap} onChange={event => patch({ minimumCap: event.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="stack-date">시세 기준일 (선택)</Label><Input className="min-h-11" id="stack-date" type="date" value={draft.asOf} onChange={event => patch({ asOf: event.target.value })} /></div>
          </fieldset>
          {invalid && <p role="alert" className="text-sm text-destructive">{invalid} 해당 블록의 ‘조건 수정’을 열어 확인해 주세요.</p>}
          <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-caption text-muted-foreground">{stored === false ? '이 브라우저에서 초안을 보존하지 못했습니다.' : '기준일을 비우면 최신 보유 시세로 찾습니다. 쌓은 조건은 이 탭에서 자동 보존됩니다.'}</p>
            <Button type="submit" className="min-h-11" disabled={busy || missing || !!invalid || !draft.conditions.length}>{busy ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}{busy ? '검색 준비 중…' : draft.conditions.length ? `${draft.conditions.length}개 조건으로 종목 찾기` : '종목 찾기'}</Button></div>
        </form>
      </div>}
    </CardContent>
  </Card>
}
