import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Info, LoaderCircle, Plus, Search } from 'lucide-react'
import { toast } from 'sonner'
import { useRecommendations } from '@/hooks/useDiscovery'
import { ErrorState } from '@/components/shared/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { StrategyConditionEditor } from '@/components/analysis/StrategyConditionEditor'
import { DISCOVERY_SCENARIOS, SCENARIO_GROUPS, scenarioGroup, type ScenarioGroup } from '@/components/analysis/discoveryScenarios'
import { MAX_STACKED_CONDITIONS, stackConditions, type PurposeDraft } from '@/components/analysis/discoveryDraft'
import type { AnalysisResult, AnalysisSpec, StrategyCondition, StrategyDefinition } from '@/components/analysis/types'
import { formatNumber } from '@/utils/format'

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
export const EMPTY_STACK: PurposeDraft = { conditions: [], market: 'all', minimumCap: '0', asOf: '', off: [] }

/** 켜 둔 블록만 — 꺼 둔 블록은 스택에 남지만 검색에서 뺀다. */
export const activeConditions = (draft: PurposeDraft) => draft.conditions.filter(c => !(draft.off ?? []).includes(c.strategy_id))

/** 쌓은 조건 → 모델 해석 없이 바로 실행되는 요청(spec 명시). */
export function stackSubmission(draft: PurposeDraft, definitions: StrategyDefinition[]): StrategySubmission {
  const conditions = activeConditions(draft)
  const lines = conditions.map(c => {
    const definition = definitions.find(d => d.id === c.strategy_id)
    const settings = Object.entries(c.params).map(([key, value]) => `${definition?.parameters[key]?.label ?? key}: ${String(value)}`)
    if (c.within_days > 1) settings.push(`최근 ${c.within_days}거래일`)
    return `- ${definition?.label ?? c.strategy_id}${settings.length ? ` (${settings.join(', ')})` : ''}`
  })
  const cap = Number(draft.minimumCap)
  return { question: `${draft.market === 'all' ? '국내 전체 시장' : draft.market}${cap ? `, 시가총액 ${draft.minimumCap}억원 이상` : ''}에서 다음 조건을 모두 만족하는 종목을 찾아줘.\n${lines.join('\n')}`,
    spec: { mode: 'catalog', market: draft.market, min_market_cap: cap * 100_000_000, as_of: draft.asOf || null, pattern: 'none', require_52w: false, require_ma: false, strategy_conditions: conditions },
    ...(draft.asOf ? { as_of: draft.asOf } : {}) }
}

/** 스택에 조건을 더하거나 뺀 새 초안 — 중복·12개 초과는 토스트로 알린다. */
function addTo(draft: PurposeDraft, incoming: StrategyCondition[]): PurposeDraft {
  const result = stackConditions(draft.conditions, incoming)
  const notes = [result.duplicate && `이미 쌓인 조건 ${result.duplicate}개는 기존 설정을 유지했습니다.`, result.overflow && `최대 ${MAX_STACKED_CONDITIONS}개라 ${result.overflow}개는 추가하지 못했습니다.`].filter(Boolean)
  if (notes.length) toast(notes.join(' '))
  return { ...draft, conditions: result.conditions }
}
const removeFrom = (draft: PurposeDraft, ids: string[]): PurposeDraft =>
  ({ ...draft, conditions: draft.conditions.filter(c => !ids.includes(c.strategy_id)), off: (draft.off ?? []).filter(id => !ids.includes(id)) })

export function DefinitionInfo({ definition }: { definition: StrategyDefinition }) {
  return <Popover><PopoverTrigger asChild><Button type="button" variant="ghost" size="icon-sm" className="size-9 shrink-0 text-muted-foreground" aria-label={`${definition.label} 계산 기준 보기`}><Info className="size-3.5" /></Button></PopoverTrigger>
    <PopoverContent align="end" className="w-72 space-y-2 break-words text-caption text-muted-foreground">
      <p className="text-sm font-medium text-foreground">{definition.label}</p>
      <p>{definition.description}</p>
      <p><span className="font-medium text-foreground">계산 기준: </span>{definition.formula}</p>
      <p>필요 자료: {definition.required_data.map(item => DATA_LABELS[item] ?? item).join(' · ')}</p>
      {!definition.available && <p className="text-hypothesis">현재 필요한 자료가 없어 판정할 수 없습니다. 실행 결과에 미평가 사유를 표시합니다.</p>}
    </PopoverContent></Popover>
}

/** 좌측 — 빠른 시작(서버 추천 조건 묶음)과 81개 카탈로그. 누르면 중앙 스택에 쌓고 다시 누르면 뺀다. */
export function ConditionPalette({ draft, definitions, busy, onChange }: {
  draft: PurposeDraft; definitions: StrategyDefinition[]; busy: boolean; onChange: (next: PurposeDraft) => void
}) {
  const [params, setParams] = useSearchParams()
  const presets = useRecommendations()
  const [search, setSearch] = useState('')
  const group = scenarioGroup(params.get('scenario'), params.get('intent') ?? '')
  const scenarios = DISCOVERY_SCENARIOS.filter(item => group === 'all' || item.group === group)
  const stacked = new Set(draft.conditions.map(c => c.strategy_id))
  const full = draft.conditions.length >= MAX_STACKED_CONDITIONS
  const term = search.trim().toLocaleLowerCase()
  const visible = definitions.filter(d => `${d.label} ${d.description}`.toLocaleLowerCase().includes(term))
  const presetConditions = (id: string) => presets.data?.items.find(item => item.id === id)?.spec.strategy_conditions ?? []
  const changeGroup = (value: ScenarioGroup) => setParams(previous => { const next = new URLSearchParams(previous); next.set('scenario', value); next.delete('intent'); return next }, { replace: true, preventScrollReset: true })
  function togglePreset(id: string) {
    const conditions = presetConditions(id)
    onChange(conditions.length && conditions.every(c => stacked.has(c.strategy_id)) ? removeFrom(draft, conditions.map(c => c.strategy_id)) : addTo(draft, conditions))
  }
  return <div className="min-w-0 space-y-5">
    <section aria-label="빠른 시작" className="space-y-2">
      <h3 className="text-sm font-medium">빠른 시작</h3>
      <ToggleGroup type="single" value={group} onValueChange={value => { if (value) changeGroup(value as ScenarioGroup) }} variant="outline" size="sm" aria-label="빠른 시작 범위" className="max-w-full flex-wrap justify-start">{SCENARIO_GROUPS.map(option => <ToggleGroupItem key={option.id} value={option.id} disabled={busy} className="min-h-9 px-2.5 text-caption">{option.label}</ToggleGroupItem>)}</ToggleGroup>
      {presets.isError && <ErrorState message="빠른 시작 조건을 불러오지 못했습니다." onRetry={() => presets.refetch()} />}
      <ul className="space-y-1">{scenarios.map(scenario => {
        const conditions = presetConditions(scenario.id)
        const applied = conditions.length > 0 && conditions.every(c => stacked.has(c.strategy_id))
        return <li key={scenario.id}><Button type="button" variant="ghost" disabled={busy || !conditions.length} aria-pressed={applied} title={scenario.description}
          className={`h-auto min-h-10 w-full justify-between gap-2 whitespace-normal px-2 py-1.5 text-left font-normal ${applied ? 'bg-primary/5 text-primary' : ''}`} onClick={() => togglePreset(scenario.id)}>
          <span className="min-w-0"><span className="block break-keep text-sm">{scenario.name}</span><span className="block text-caption text-muted-foreground">{scenario.tag} · 조건 {conditions.length || '–'}개</span></span>
          {applied ? <Check className="size-4 shrink-0" aria-hidden="true" /> : <Plus className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
        </Button></li>
      })}</ul>
    </section>
    <section aria-label="조건 목록" className="space-y-2">
      <h3 className="text-sm font-medium">조건 목록 <span className="font-normal text-muted-foreground">{definitions.length}</span></h3>
      <div className="relative"><Label htmlFor="stack-search" className="sr-only">조건 찾기</Label><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input id="stack-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="이평, 신고가, RSI…" className="min-h-10 pl-9" /></div>
      {!visible.length ? <div className="space-y-2 py-6 text-center"><p className="text-sm text-muted-foreground">검색어에 맞는 조건이 없습니다.</p><Button type="button" variant="outline" size="sm" onClick={() => setSearch('')}>검색 지우기</Button></div>
        : <div className="space-y-4">{CATEGORIES.map(category => {
          const items = visible.filter(d => d.category === category)
          return items.length > 0 && <div key={category} className="space-y-1"><h4 className="px-1 text-caption font-medium text-muted-foreground">{category} {items.length}</h4><ul>{items.map(definition => {
            const on = stacked.has(definition.id)
            return <li key={definition.id} className="flex items-center gap-1">
              <Button type="button" variant="ghost" disabled={busy || (!on && full)} aria-pressed={on} className={`h-auto min-h-9 min-w-0 flex-1 justify-between gap-2 whitespace-normal px-2 py-1.5 text-left text-sm font-normal ${on ? 'bg-primary/5 text-primary' : ''}`}
                onClick={() => onChange(on ? removeFrom(draft, [definition.id]) : addTo(draft, [{ strategy_id: definition.id, params: { ...definition.defaults }, within_days: 1 }]))}>
                <span className="min-w-0 break-keep">{definition.label}{!definition.available && <Badge variant="secondary" className="ml-1.5 font-normal">자료 필요</Badge>}</span>
                {on ? <Check className="size-4 shrink-0" aria-hidden="true" /> : <Plus className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
              </Button>
              <DefinitionInfo definition={definition} />
            </li>
          })}</ul></div>
        })}</div>}
    </section>
  </div>
}

/** 중앙 — 쌓은 블록(켜기·끄기·수정·제거)과 마지막 결과의 블록별 집계, 검색 대상, 하단 고정 검색 버튼. */
export function ConditionStack({ draft, definitions, busy, computing, result, resultConditions, status, onChange, onRunNow, runDisabled }: {
  draft: PurposeDraft; definitions: StrategyDefinition[]; busy: boolean; computing: boolean
  result: AnalysisResult | null; resultConditions: string[]; status: string
  onChange: (next: PurposeDraft) => void; onRunNow: () => void; runDisabled: boolean
}) {
  const off = draft.off ?? []
  const active = activeConditions(draft)
  const funnel = result?.condition_funnel
  const ranked = active.some(c => c.strategy_id.startsWith('rank_'))
  const matched = result?.counts.matched ?? 0
  const patch = (next: Partial<PurposeDraft>) => onChange({ ...draft, ...next })
  return <form aria-label="쌓은 검색 조건" onSubmit={event => { event.preventDefault(); onRunNow() }} className="min-w-0 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-medium">내 조건 {active.length}/{draft.conditions.length} <span className="font-normal text-muted-foreground">· 모두 만족</span></h3>
      {draft.conditions.length > 0 && <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => patch({ conditions: [], off: [] })}>모두 비우기</Button>}
    </div>
    {!draft.conditions.length ? <div className="rounded-xl border border-dashed p-6 text-center"><p className="text-sm font-medium">아직 쌓인 조건이 없습니다</p><p className="mt-1 text-caption text-muted-foreground">빠른 시작이나 조건 목록의 +로 블록을 추가하세요.</p></div>
      : <ol className="space-y-2" aria-label="쌓은 조건 블록">{draft.conditions.map((condition, index) => {
        const definition = definitions.find(d => d.id === condition.strategy_id)
        const on = !off.includes(condition.strategy_id)
        const stat = funnel?.conditions.find(c => c.strategy_id === condition.strategy_id)
        const label = definition?.label ?? condition.strategy_id
        return <li key={condition.strategy_id} className={`flex min-w-0 items-start gap-2.5 ${on ? '' : 'opacity-60'}`}>
          <Switch className="mt-3" checked={on} disabled={busy} aria-label={`${label} 사용`}
            onCheckedChange={next => patch({ off: next ? off.filter(id => id !== condition.strategy_id) : [...off, condition.strategy_id] })} />
          <div className="min-w-0 flex-1 space-y-1">
            {definition ? <StrategyConditionEditor definition={definition} condition={condition} busy={busy}
              onChange={next => patch({ conditions: draft.conditions.map((c, i) => i === index ? next : c) })} onRemove={() => onChange(removeFrom(draft, [condition.strategy_id]))} />
              : <div className="flex items-center justify-between gap-2 rounded-lg border p-3"><p role="alert" className="text-sm text-destructive">더 이상 지원하지 않는 조건입니다.</p><Button type="button" variant="ghost" size="sm" onClick={() => onChange(removeFrom(draft, [condition.strategy_id]))}>제거</Button></div>}
            {on && stat && funnel && resultConditions.includes(condition.strategy_id) && <p className={`flex flex-wrap items-center gap-2 pl-1 text-caption text-muted-foreground ${computing ? 'opacity-50' : ''}`}>
              <span className="tabular-nums">통과 {formatNumber(stat.passed)} / {formatNumber(funnel.evaluated)}</span>
              {!ranked && stat.sole_blocker > 0 && <Badge variant="outline" className={`font-normal tabular-nums ${matched === 0 ? 'border-primary/50 text-primary' : ''}`}>빼면 +{formatNumber(stat.sole_blocker)}종목</Badge>}
            </p>}
          </div>
        </li>
      })}</ol>}
    <fieldset disabled={busy} className="grid min-w-0 grid-cols-1 gap-3 border-t pt-4 @lg:grid-cols-3"><legend className="sr-only">검색 대상과 시점</legend>
      <div className="space-y-1.5"><Label htmlFor="stack-market">시장</Label><Select value={draft.market} onValueChange={value => patch({ market: value as PurposeDraft['market'] })} disabled={busy}><SelectTrigger id="stack-market" className="min-h-10 w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">국내 전체</SelectItem><SelectItem value="KOSPI">KOSPI</SelectItem><SelectItem value="KOSDAQ">KOSDAQ</SelectItem></SelectContent></Select></div>
      <div className="space-y-1.5"><Label htmlFor="stack-cap">최소 시총 (억원)</Label><Input className="min-h-10" id="stack-cap" type="number" required min={0} max={1_000_000_000} step="any" value={draft.minimumCap} onChange={event => patch({ minimumCap: event.target.value })} /></div>
      <div className="space-y-1.5"><Label htmlFor="stack-date">시세 기준일</Label><Input className="min-h-10" id="stack-date" type="date" value={draft.asOf} onChange={event => patch({ asOf: event.target.value })} /></div>
    </fieldset>
    {ranked && <p className="text-caption text-muted-foreground">순위 조건이 있으면 통과 집단에 따라 순위가 달라져 ‘빼면 몇 종목’은 표시하지 않습니다.</p>}
    <div className="sticky bottom-0 -mx-3 flex flex-wrap items-center justify-between gap-2 border-t bg-card px-3 py-3">
      <p role="status" aria-live="polite" className="min-w-0 flex-1 text-caption text-muted-foreground">{status}</p>
      <Button type="submit" className="min-h-10" disabled={runDisabled}>{computing ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}{computing ? '찾는 중…' : `${active.length}개 조건으로 검색`}</Button>
    </div>
  </form>
}
