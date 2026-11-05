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
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { StrategyConditionEditor } from '@/components/analysis/StrategyConditionEditor'
import { SCENARIO_GROUPS, scenarioGroup, type ScenarioGroup } from '@/components/analysis/discoveryScenarios'
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
  const universe = draft.universe ? `${draft.universe.label} ${draft.universe.codes.length}종목 중 ` : ''
  return { question: `${universe}${draft.market === 'all' ? '국내 전체 시장' : draft.market}${cap ? `, 시가총액 ${draft.minimumCap}억원 이상` : ''}에서 다음 조건을 모두 만족하는 종목을 찾아줘.\n${lines.join('\n')}`,
    spec: { mode: 'catalog', market: draft.market, min_market_cap: cap * 100_000_000, as_of: draft.asOf || null, pattern: 'none', require_52w: false, require_ma: false, strategy_conditions: conditions, ...(draft.universe ? { universe_codes: draft.universe.codes } : {}) },
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
  return <Popover><PopoverTrigger asChild><Button type="button" variant="ghost" size="icon-sm" className="size-7 shrink-0 rounded-none text-ink-3 max-md:size-9" aria-label={`${definition.label} 계산 기준 보기`}><Info className="size-3.5" /></Button></PopoverTrigger>
    <PopoverContent align="end" className="w-72 space-y-2 break-words text-caption text-muted-foreground">
      <p className="text-sm font-medium text-foreground">{definition.label}</p>
      <p>{definition.description}</p>
      <p><span className="font-medium text-foreground">계산 기준: </span>{definition.formula}</p>
      <p>필요 자료: {definition.required_data.map(item => DATA_LABELS[item] ?? item).join(' · ')}</p>
      {!definition.available && <p className="text-warn">현재 필요한 자료가 없어 판정할 수 없습니다. 실행 결과에 미평가 사유를 표시합니다.</p>}
    </PopoverContent></Popover>
}

/** 좌측 — 조건 목록(시안 Discover): 검색 · 상황 세그먼트 · 빠른 시작 칩 줄 · 분류별 조건 행(+). 누르면 중앙 스택에 쌓고 다시 누르면 뺀다.
 *  세그먼트는 그 상황의 빠른 시작 묶음에 든 조건만 보인다('모든 상황' = 전체). 검색어가 있으면 전체에서 찾는다. */
export function ConditionPalette({ draft, definitions, busy, onChange }: {
  draft: PurposeDraft; definitions: StrategyDefinition[]; busy: boolean; onChange: (next: PurposeDraft) => void
}) {
  const [params, setParams] = useSearchParams()
  const presets = useRecommendations()
  const [search, setSearch] = useState('')
  const all = presets.data?.items ?? []
  const group = scenarioGroup(params.get('scenario'), params.get('intent') ?? '', all)
  const scenarios = all.filter(item => item.scenario && (group === 'all' || item.scenario === group))
  const stacked = new Set(draft.conditions.map(c => c.strategy_id))
  const full = draft.conditions.length >= MAX_STACKED_CONDITIONS
  const term = search.trim().toLocaleLowerCase()
  const inScenario = new Set(scenarios.flatMap(item => (item.spec.strategy_conditions ?? []).map(c => c.strategy_id)))
  const scoped = group === 'all' || term || !inScenario.size ? definitions : definitions.filter(d => inScenario.has(d.id) || stacked.has(d.id))
  const visible = scoped.filter(d => `${d.label} ${d.description}`.toLocaleLowerCase().includes(term))
  const presetConditions = (id: string) => presets.data?.items.find(item => item.id === id)?.spec.strategy_conditions ?? []
  const changeGroup = (value: ScenarioGroup) => setParams(previous => { const next = new URLSearchParams(previous); next.set('scenario', value); next.delete('intent'); return next }, { replace: true, preventScrollReset: true })
  function togglePreset(id: string) {
    const conditions = presetConditions(id)
    onChange(conditions.length && conditions.every(c => stacked.has(c.strategy_id)) ? removeFrom(draft, conditions.map(c => c.strategy_id)) : addTo(draft, conditions))
  }
  return <section aria-label="조건 목록" className="min-w-0 space-y-3">
    <h3 className="text-section font-semibold">조건 목록 <span className="tabular-nums">{definitions.length}</span></h3>
    <div className="relative"><Label htmlFor="stack-search" className="sr-only">조건 찾기</Label><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-[13px] -translate-y-1/2 text-ink-3" /><Input id="stack-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="이평, 신고가, RSI…" className="h-[34px] rounded-full border-0 bg-chip pl-8 text-[13px] shadow-none max-md:min-h-10" /></div>
    <ToggleGroup type="single" value={group} onValueChange={value => { if (value) changeGroup(value as ScenarioGroup) }} size="sm" aria-label="상황" className="max-w-full flex-wrap justify-start">{SCENARIO_GROUPS.map(option => <ToggleGroupItem key={option.id} value={option.id} disabled={busy} className="h-[30px] px-3 text-[13px] max-md:min-h-9">{option.label}</ToggleGroupItem>)}</ToggleGroup>
    {presets.isError && <ErrorState message="빠른 시작 조건을 불러오지 못했습니다." onRetry={() => presets.refetch()} />}
    {presets.isPending ? <div className="flex gap-1.5">{[0, 1, 2].map(i => <Skeleton key={i} className="h-7 w-20 rounded-full" />)}</div>
      : scenarios.length > 0 && <div role="group" aria-label="빠른 시작" className="flex flex-wrap gap-1.5">{scenarios.map(scenario => {
        const conditions = presetConditions(scenario.id)
        const applied = conditions.length > 0 && conditions.every(c => stacked.has(c.strategy_id))
        return <Button key={scenario.id} type="button" variant="outline" size="xs" disabled={busy || !conditions.length} aria-pressed={applied} title={`${scenario.purpose} · 조건 ${conditions.length || '–'}개`}
          className={`h-7 max-w-full gap-1 rounded-full px-2.5 text-[12px] font-medium shadow-none ${applied ? 'border-action bg-action text-action-ink hover:bg-action hover:text-action-ink' : 'text-ink-2'}`} onClick={() => togglePreset(scenario.id)}>
          {applied ? <Check className="size-3 shrink-0" aria-hidden="true" /> : <Plus className="size-3 shrink-0" aria-hidden="true" />}<span className="truncate">{scenario.name}</span>
        </Button>
      })}</div>}
    {!visible.length ? <div className="space-y-2 py-6 text-center"><p className="text-sm text-muted-foreground">검색어에 맞는 조건이 없습니다.</p><Button type="button" variant="outline" size="sm" onClick={() => setSearch('')}>검색 지우기</Button></div>
      : <div className="space-y-1">{CATEGORIES.map(category => {
        const items = visible.filter(d => d.category === category)
        return items.length > 0 && <div key={category} className="flex flex-col gap-0.5"><h4 className="pb-0.5 pt-1.5 text-xs font-normal text-ink-3">{category}</h4><ul className="flex flex-col gap-0.5">{items.map(definition => {
          const on = stacked.has(definition.id)
          return <li key={definition.id} className={`group/row flex items-center ${on ? 'bg-chip' : ''}`}>
            <Button type="button" variant="ghost" disabled={busy || (!on && full)} aria-pressed={on} className="h-auto min-h-[31px] min-w-0 flex-1 justify-between gap-2 whitespace-normal rounded-none px-2 py-1.5 text-left text-[13px] font-normal hover:bg-chip max-md:min-h-9"
              onClick={() => onChange(on ? removeFrom(draft, [definition.id]) : addTo(draft, [{ strategy_id: definition.id, params: { ...definition.defaults }, within_days: 1 }]))}>
              <span className="min-w-0 break-keep">{definition.label}{!definition.available && <Badge variant="secondary" className="ml-1.5 font-normal">자료 필요</Badge>}</span>
              {on ? <Check className="size-[13px] shrink-0" aria-hidden="true" /> : <Plus className="size-[13px] shrink-0" aria-hidden="true" />}
            </Button>
            <DefinitionInfo definition={definition} />
          </li>
        })}</ul></div>
      })}</div>}
  </section>
}

/** 중앙 — 쌓은 블록(켜기·끄기·수정·제거)과 마지막 결과의 블록별 집계, 검색 대상, 하단 고정 검색 버튼. */
export function ConditionStack({ draft, definitions, busy, computing, result, resultConditions, status, warning, onChange, onRunNow, runDisabled }: {
  draft: PurposeDraft; definitions: StrategyDefinition[]; busy: boolean; computing: boolean
  result: AnalysisResult | null; resultConditions: string[]; status: string
  /** 화면에 보일 경고(입력 오류·초안 보존 실패) — 그 밖의 상태 문장은 스크린리더에만(시안: 버튼만) */
  warning?: string | null
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
      <h3 className="text-section font-semibold">내 조건 {active.length}/{draft.conditions.length} · 모두 만족</h3>
      {draft.conditions.length > 0 && <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => patch({ conditions: [], off: [] })}>모두 비우기</Button>}
    </div>
    {draft.universe && <div className="flex items-center justify-between gap-2 border bg-muted/40 px-3 py-2 text-sm">
      <span className="min-w-0 truncate">검색 범위 · {draft.universe.label} <span className="tabular-nums text-muted-foreground">{formatNumber(draft.universe.codes.length)}종목</span></span>
      <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => patch({ universe: null })} aria-label="검색 범위 지우기">지우기</Button>
    </div>}
    {!draft.conditions.length ? <div className="border border-dashed border-line-2 p-6 text-center"><p className="text-sm font-medium">아직 쌓인 조건이 없습니다</p><p className="mt-1 text-caption text-muted-foreground">조건 목록의 +나 빠른 시작 칩으로 블록을 추가하세요.</p></div>
      : <ol className="space-y-2" aria-label="쌓은 조건 블록">{draft.conditions.map((condition, index) => {
        const definition = definitions.find(d => d.id === condition.strategy_id)
        const on = !off.includes(condition.strategy_id)
        const stat = funnel?.conditions.find(c => c.strategy_id === condition.strategy_id)
        const label = definition?.label ?? condition.strategy_id
        const toggle = <Switch checked={on} disabled={busy} aria-label={`${label} 사용`}
          onCheckedChange={next => patch({ off: next ? off.filter(id => id !== condition.strategy_id) : [...off, condition.strategy_id] })} />
        const stats = on && stat && funnel && resultConditions.includes(condition.strategy_id) ? <p className={`flex flex-wrap items-center gap-1.5 ${computing ? 'opacity-50' : ''}`}>
          <span className="inline-flex h-[22px] items-center rounded-md bg-chip px-2 text-xs font-medium tabular-nums text-ink-2">통과 {formatNumber(stat.passed)} / {formatNumber(funnel.evaluated)}</span>
          {!ranked && stat.sole_blocker > 0 && <span className={`inline-flex h-[22px] items-center rounded-md border border-line-2 px-2 text-xs font-medium tabular-nums ${matched === 0 ? 'text-warn' : 'text-ink-2'}`}>빼면 +{formatNumber(stat.sole_blocker)}종목</span>}
        </p> : null
        return <li key={condition.strategy_id} className={`min-w-0 ${on ? '' : 'opacity-60'}`}>
          {definition ? <StrategyConditionEditor definition={definition} condition={condition} busy={busy} number={index + 1} toggle={toggle} footer={stats}
            onChange={next => patch({ conditions: draft.conditions.map((c, i) => i === index ? next : c) })} onRemove={() => onChange(removeFrom(draft, [condition.strategy_id]))} />
            : <div className="flex items-center justify-between gap-2 border p-3"><p role="alert" className="text-sm text-destructive">더 이상 지원하지 않는 조건입니다.</p><Button type="button" variant="ghost" size="sm" onClick={() => onChange(removeFrom(draft, [condition.strategy_id]))}>제거</Button></div>}
        </li>
      })}</ol>}
    <fieldset disabled={busy} className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1.5 text-[12.5px]"><legend className="sr-only">검색 대상과 시점</legend>
      <Label htmlFor="stack-market" className="text-[12.5px] font-normal text-ink-3">시장</Label><Select value={draft.market} onValueChange={value => patch({ market: value as PurposeDraft['market'] })} disabled={busy}><SelectTrigger id="stack-market" className="h-8 w-full text-[12.5px] max-md:min-h-10"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">국내 전체</SelectItem><SelectItem value="KOSPI">KOSPI</SelectItem><SelectItem value="KOSDAQ">KOSDAQ</SelectItem></SelectContent></Select>
      <Label htmlFor="stack-cap" className="text-[12.5px] font-normal text-ink-3">최소 시총 (억원)</Label><Input className="h-8 font-mono text-[12.5px] tabular-nums max-md:min-h-10" id="stack-cap" type="number" required min={0} max={1_000_000_000} step="any" value={draft.minimumCap} onChange={event => patch({ minimumCap: event.target.value })} />
      <Label htmlFor="stack-date" className="text-[12.5px] font-normal text-ink-3">시세 기준일</Label><Input className="h-8 font-mono text-[12.5px] tabular-nums max-md:min-h-10" id="stack-date" type="date" value={draft.asOf} onChange={event => patch({ asOf: event.target.value })} />
    </fieldset>
    {ranked && <p className="text-caption text-muted-foreground">순위 조건이 있으면 통과 집단에 따라 순위가 달라져 ‘빼면 몇 종목’은 표시하지 않습니다.</p>}
    {/* <768은 하단 탭바가 fixed로 덮으므로 그 위에 붙인다 */}
    <div className="sticky bottom-0 max-md:bottom-[calc(var(--tabbar-height)+env(safe-area-inset-bottom))] -mx-4 flex flex-col gap-2 bg-card px-4 py-3">
      <p role="status" aria-live="polite" className={warning ? 'text-caption text-warn' : 'sr-only'}>{warning || status}</p>
      <Button type="submit" className="min-h-9 w-full" disabled={runDisabled}>{computing ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}{computing ? '찾는 중…' : `${active.length}개 조건으로 검색`}</Button>
    </div>
  </form>
}
