import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, LoaderCircle, Search, X } from 'lucide-react'
import { API_BASE } from '@/api/client'
import { ErrorState } from '@/components/shared/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import type { AnalysisSpec, StrategyCondition, StrategyDefinition } from '@/components/analysis/types'

const CATEGORIES = ['시세동향', '지표신호', '가격 구조', '순위종목'] as const
const DATA_LABELS: Record<string, string> = {
  daily_ohlcv: '일봉 시세', ohlcv: '시세와 거래량', intraday_10m: '10분봉 시세',
  ohlcv_10m: '10분봉 시세', trading_value: '실제 거래대금', shares: '상장주식 수',
  shares_outstanding: '상장주식 수', market_cap: '시가총액',
  open: '시가', high: '고가', low: '저가', close: '종가', volume: '거래량', timestamp: '10분봉 시각',
}
const OPTION_LABELS: Record<string, string> = { up: '상향', down: '하향', both: '양방향', high: '고가', low: '저가', close: '종가', open: '시가' }

export interface StrategySubmission {
  question: string
  spec: Partial<AnalysisSpec>
  as_of?: string
}

function StrategyDefinitionText({ definition }: { definition: StrategyDefinition }) {
  return <div className="space-y-2 break-words text-caption text-muted-foreground">
    <p>{definition.description}</p>
    <p><span className="font-medium text-foreground">계산 기준: </span>{definition.formula}</p>
    <p>필요 자료: {definition.required_data.map(item => DATA_LABELS[item] ?? item).join(' · ')}</p>
    {!definition.available && <p className="text-hypothesis">현재 필요한 자료가 없어 판정할 수 없습니다. 실행 결과에도 미평가 사유를 표시합니다.</p>}
  </div>
}

export function StrategyLibrary({ busy, onStart }: { busy: boolean; onStart: (submission: StrategySubmission) => Promise<void> }) {
  const catalog = useQuery({
    queryKey: ['market-analysis', 'strategies'],
    queryFn: async ({ signal }): Promise<{ version: string; items: StrategyDefinition[] }> => {
      const response = await fetch(`${API_BASE}/api/analysis/strategies`, { signal })
      if (!response.ok) throw new Error('전략 도구를 불러오지 못했습니다.')
      return response.json()
    },
    staleTime: 60_000,
    retry: 1,
  })
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('전체')
  const [conditions, setConditions] = useState<StrategyCondition[]>([])
  const [market, setMarket] = useState<AnalysisSpec['market']>('all')
  const [minimumCap, setMinimumCap] = useState('0')
  const [asOf, setAsOf] = useState('')
  const definitions = catalog.data?.items ?? []
  const normalizedSearch = search.trim().toLocaleLowerCase()
  const visible = definitions.filter(item => (category === '전체' || item.category === category)
    && `${item.label} ${item.description}`.toLocaleLowerCase().includes(normalizedSearch))
  const selected = conditions.flatMap(condition => {
    const definition = definitions.find(item => item.id === condition.strategy_id)
    return definition ? [{ condition, definition }] : []
  })
  const hasUnavailable = selected.some(({ definition }) => !definition.available)

  function toggle(definition: StrategyDefinition) {
    setConditions(previous => previous.some(item => item.strategy_id === definition.id)
      ? previous.filter(item => item.strategy_id !== definition.id)
      : previous.length < 12 ? [...previous, { strategy_id: definition.id, params: { ...definition.defaults }, within_days: 1 }] : previous)
  }
  function update(id: string, patch: Partial<StrategyCondition>) {
    setConditions(previous => previous.map(item => item.strategy_id === id ? { ...item, ...patch } : item))
  }
  async function submit() {
    if (!selected.length || busy) return
    const labels = selected.map(({ definition, condition }) => {
      const settings = Object.entries(condition.params).filter(([key, value]) => value !== definition.defaults[key]).map(([key, value]) => `${definition.parameters[key]?.label ?? key}: ${String(value)}`)
      if (condition.within_days > 1) settings.push(`최근 ${condition.within_days}거래일`)
      return `${definition.label}${settings.length ? ` (${settings.join(', ')})` : ''}`
    })
    const question = `${market === 'all' ? '국내 전체 시장' : market}에서 ${Number(minimumCap) === 0 ? '' : `시가총액 ${minimumCap}억원 이상이며 `}${labels.join(', ')} 조건을 모두 만족하는 종목을 찾아줘`
    await onStart({ question, spec: { mode: 'catalog', market, min_market_cap: Number(minimumCap) * 100_000_000, pattern: 'none', require_52w: false, require_ma: false, strategy_conditions: conditions }, ...(asOf ? { as_of: asOf } : {}) })
  }

  return <Card>
    <CardHeader className="space-y-2"><CardTitle className="text-card-title">전략 도구</CardTitle><p className="text-sm text-muted-foreground">사용할 조건을 선택하고 기간·계산 기준을 조정하세요. 선택한 조건을 모두 충족하는 종목을 찾습니다.</p></CardHeader>
    <CardContent className="space-y-4">
      {catalog.isPending && <div role="status" aria-label="전략 도구 불러오는 중" className="space-y-3"><Skeleton className="h-10 w-full" /><Skeleton className="h-48 w-full" /></div>}
      {catalog.isError && <ErrorState message="전략 도구를 불러오지 못했습니다." onRetry={() => catalog.refetch()} />}
      {catalog.data && <form onSubmit={event => { event.preventDefault(); void submit() }} className="space-y-5">
        <fieldset disabled={busy} className="min-w-0 space-y-4">
          <legend className="sr-only">분석에 사용할 전략 선택</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_140px]">
            <div className="space-y-1.5"><Label htmlFor="strategy-search">전략 검색</Label><div className="relative"><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" /><Input id="strategy-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="이평, 신고가, MACD…" className="pl-9" /></div></div>
            <div className="space-y-1.5"><Label htmlFor="strategy-category">분류</Label><Select value={category} onValueChange={setCategory} disabled={busy}><SelectTrigger id="strategy-category"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="전체">전체</SelectItem>{CATEGORIES.map(item => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent></Select></div>
          </div>
          <p role="status" className="text-caption text-muted-foreground">전체 {definitions.length}개 · 검색 {visible.length}개 · 선택 {conditions.length}/12개</p>
          {!definitions.length ? <p className="py-6 text-center text-sm text-muted-foreground">등록된 전략 도구가 없습니다.</p> : !visible.length ? <div className="space-y-2 py-5 text-center"><p className="text-sm text-muted-foreground">검색 조건에 맞는 전략이 없습니다.</p><Button type="button" variant="outline" size="sm" onClick={() => { setSearch(''); setCategory('전체') }}>검색 초기화</Button></div> : <div className="max-h-[32rem] space-y-5 overflow-y-auto rounded-lg border p-3 sm:p-4">
            {CATEGORIES.map(group => {
              const items = visible.filter(item => item.category === group)
              return items.length > 0 && <section key={group} aria-label={group} className="space-y-2"><h3 className="text-sm font-medium">{group} <span className="font-normal text-muted-foreground">{items.length}</span></h3><div className="divide-y">{items.map(definition => {
                const checked = conditions.some(condition => condition.strategy_id === definition.id)
                return <div key={definition.id} className="py-2.5">
                  <div className="flex min-h-9 items-center gap-3"><Checkbox id={`tool-${definition.id}`} checked={checked} disabled={busy || (!checked && conditions.length >= 12)} onCheckedChange={() => toggle(definition)} aria-label={definition.label} /><Label htmlFor={`tool-${definition.id}`} className="min-w-0 flex-1 cursor-pointer text-sm font-normal">{definition.label}</Label><span className="flex shrink-0 flex-col items-end gap-1 sm:flex-row"><Badge variant="outline" className="font-normal">{definition.timeframe === '10m' ? '10분봉' : '일봉'}</Badge>{!definition.available && <Badge variant="secondary" className="font-normal">자료 필요</Badge>}</span></div>
                  <Collapsible className="ml-7 mt-1"><CollapsibleTrigger asChild><Button type="button" variant="ghost" size="sm" className="h-auto px-0 py-1 text-caption text-muted-foreground">계산 기준 보기<span className="sr-only"> · {definition.label}</span><ChevronDown className="size-3" /></Button></CollapsibleTrigger><CollapsibleContent className="pb-1 pt-2"><StrategyDefinitionText definition={definition} /></CollapsibleContent></Collapsible>
                </div>
              })}</div></section>
            })}
          </div>}
          {!!selected.length && <section aria-label="선택한 전략 설정" className="space-y-4 rounded-lg bg-muted/40 p-3 sm:p-4">
            <div className="space-y-1"><h3 className="text-sm font-medium">선택한 조건 {selected.length}개 · 모두 만족 (AND)</h3><p className="text-caption text-muted-foreground">순위는 다른 조건을 통과한 종목 사이에서 계산합니다. 여러 순위 조건도 모두 만족해야 합니다.</p></div>
            {selected.map(({ condition, definition }) => <fieldset key={definition.id} className="min-w-0 space-y-3 border-t pt-3"><legend className="sr-only">{definition.label} 설정</legend>
              <div className="flex items-center justify-between gap-2"><span className="text-sm font-medium">{definition.label}</span><Button type="button" size="icon-sm" variant="ghost" aria-label={`${definition.label} 선택 해제`} onClick={() => toggle(definition)}><X className="size-4" /></Button></div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {Object.entries(definition.parameters).map(([key, parameter]) => <div key={key} className="min-w-0 space-y-1.5"><Label htmlFor={`strategy-${definition.id}-${key}`}>{parameter.label}</Label>
                  {parameter.options ? <Select disabled={busy} value={String(condition.params[key] ?? '')} onValueChange={value => update(definition.id, { params: { ...condition.params, [key]: value } })}><SelectTrigger id={`strategy-${definition.id}-${key}`}><SelectValue /></SelectTrigger><SelectContent>{parameter.options.map(option => <SelectItem key={option} value={option}>{OPTION_LABELS[option] ?? option}</SelectItem>)}</SelectContent></Select>
                    : parameter.type === 'boolean' ? <Checkbox id={`strategy-${definition.id}-${key}`} disabled={busy} checked={!!condition.params[key]} onCheckedChange={checked => update(definition.id, { params: { ...condition.params, [key]: checked === true } })} />
                      : <Input id={`strategy-${definition.id}-${key}`} type={parameter.type === 'string' ? 'text' : 'number'} value={String(condition.params[key] ?? '')} min={parameter.min} max={parameter.max} step={parameter.step ?? (parameter.type === 'integer' ? 1 : 'any')} required onChange={event => update(definition.id, { params: { ...condition.params, [key]: parameter.type === 'string' || event.target.value === '' ? event.target.value : Number(event.target.value) } })} />}
                </div>)}
                {definition.category !== '순위종목' && definition.timeframe === '1d' && <div className="space-y-1.5"><Label htmlFor={`strategy-${definition.id}-within`}>최근 판정 범위 (거래일)</Label><Input id={`strategy-${definition.id}-within`} type="number" min={1} max={250} step={1} required value={condition.within_days || ''} onChange={event => update(definition.id, { within_days: Number(event.target.value) })} /><p className="text-caption text-muted-foreground">1이면 기준일만, 2 이상이면 기간 중 한 번 이상 충족</p></div>}
              </div>
            </fieldset>)}
            {hasUnavailable && <p className="text-caption text-hypothesis">자료가 필요한 조건을 선택했습니다. 필요한 자료가 없는 종목은 통과·탈락 대신 판단 불가로 표시됩니다.</p>}
          </section>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5"><Label htmlFor="strategy-market">시장</Label><Select disabled={busy} value={market} onValueChange={value => setMarket(value as AnalysisSpec['market'])}><SelectTrigger id="strategy-market"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">국내 전체</SelectItem><SelectItem value="KOSPI">KOSPI</SelectItem><SelectItem value="KOSDAQ">KOSDAQ</SelectItem></SelectContent></Select></div>
            <div className="space-y-1.5"><Label htmlFor="strategy-market-cap">최소 시가총액 (억원)</Label><Input id="strategy-market-cap" type="number" min={0} max={1_000_000_000} step="any" required value={minimumCap} onChange={event => setMinimumCap(event.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="strategy-as-of">기준일 (선택)</Label><Input id="strategy-as-of" type="date" value={asOf} onChange={event => setAsOf(event.target.value)} /></div>
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-caption text-muted-foreground">기준일을 비우면 최신 보유일을 사용합니다.</p><Button type="submit" disabled={busy || !selected.length}>{busy && <LoaderCircle className="size-4 animate-spin" />}선택한 {selected.length}개 조건으로 분석</Button></div>
      </form>}
    </CardContent>
  </Card>
}
