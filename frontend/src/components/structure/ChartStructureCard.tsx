import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Bell, ExternalLink, Search } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import CandlestickChart from '@/components/charts/CandlestickChart'
import { GroupPicker } from '@/components/follow/GroupPicker'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Slider } from '@/components/ui/slider'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ErrorState } from '@/components/shared/ErrorState'
import { useAppendMemberRule } from '@/hooks/useGroups'
import { formatNumber, formatPercent, formatPrice } from '@/utils/format'

/** 종목의 차트에 채널·추세선·지지/저항 레벨을 그리는 결정적 계산 (docs/specs/chart-structure.md, D-195·D-196). 모델 호출 0. */
export type StructureKind = 'channel' | 'trendline_high' | 'trendline_low' | 'levels'
export type StructureFit = 'two_point' | 'regression'
export interface StructureParams { code: string; market: 'kr' | 'us'; kind: StructureKind; window: string; swing: number; fit: StructureFit }
export interface StructureCondition { strategy_id: string; label: string; params: Record<string, unknown>; within_days: number; phrase: string; note: string }
export interface StructureLevel { price: number; touches: number; first: string; last_touch: string; role: 'support' | 'resistance'; sides: string[] }
export interface StructureResult {
  code: string; name: string; market: 'kr' | 'us'; kind: StructureKind; fit: StructureFit; swing: number; requested_swing: number
  window: { from: string; to: string; requested_from: string; sessions: number }
  candles: { time: string; open: number; high: number; low: number; close: number }[]
  pivots: { time: string; price: number; side: 'high' | 'low'; anchor: boolean }[]
  lines: { id: string; label: string; points: { time: string; value: number }[] }[]
  summary: { upper_now?: number; lower_now?: number; line_now?: number; close: number; position_pct?: number | null; width_pct?: number | null; distance_pct?: number | null; touches_upper?: number; touches_lower?: number; touches?: number; slope_pct_per_session: number | null; sessions: number; levels?: StructureLevel[]; nearest_resistance?: number | null; nearest_support?: number | null; resistance_distance_pct?: number | null; support_distance_pct?: number | null }
  conditions: StructureCondition[]
  notes: string[]
}

export const KIND_LABEL: Record<StructureKind, string> = { channel: '채널', trendline_high: '고점 추세선', trendline_low: '저점 추세선', levels: '지지·저항 레벨' }
export const WINDOW_LABEL: Record<string, string> = { ytd: '올해', '3m': '3개월', '6m': '6개월', '1y': '1년', '2y': '2년' }

/** 바로 꺼내 쓰는 구조 프리셋. 문장은 종목 발견 질문에 그대로 넣을 수 있게 해석 규칙과 같은 단어를 쓴다. */
export const STRUCTURE_PRESETS: { id: string; label: string; purpose: string; params: Omit<StructureParams, 'code' | 'market'>; phrase: string }[] = [
  { id: 'ytd-big-channel', label: '올해 큰 채널', purpose: '올해 전고점을 이은 채널 안에서 현재가가 어디인지', params: { kind: 'channel', window: 'ytd', swing: 10, fit: 'two_point' }, phrase: '올해 전고점들을 기반으로 큰 채널을 그려줘' },
  { id: '6m-channel', label: '6개월 채널', purpose: '중기 파동의 상·하단과 채널 폭', params: { kind: 'channel', window: '6m', swing: 5, fit: 'two_point' }, phrase: '최근 6개월 채널을 그려줘' },
  { id: '1y-support-trend', label: '1년 저점 추세선', purpose: '상승 추세의 지지선이 아직 살아 있는지', params: { kind: 'trendline_low', window: '1y', swing: 5, fit: 'two_point' }, phrase: '1년 저점들을 연결한 추세선을 그려줘' },
  { id: '3m-resistance-trend', label: '3개월 고점 추세선', purpose: '단기 하락 추세선을 돌파했는지', params: { kind: 'trendline_high', window: '3m', swing: 3, fit: 'two_point' }, phrase: '최근 3개월 고점을 연결한 추세선을 그려줘' },
  { id: '1y-levels', label: '1년 지지·저항 레벨', purpose: '여러 번 닿은 가격대와 현재가의 거리', params: { kind: 'levels', window: '1y', swing: 5, fit: 'two_point' }, phrase: '1년 지지·저항 레벨을 그려줘' },
  { id: 'ytd-regression-channel', label: '올해 회귀 채널', purpose: '고점 전체를 평균한 완만한 채널', params: { kind: 'channel', window: 'ytd', swing: 5, fit: 'regression' }, phrase: '올해 고점 전체를 회귀로 적합한 채널을 그려줘' },
]

export function useChartStructure(params: StructureParams, enabled = true) {
  return useQuery({
    queryKey: ['spine', 'chart-structure', params],
    queryFn: async () => (await api.get<StructureResult>(`/api/spine/chart-structure/${params.code}`, { params: { market: params.market, kind: params.kind, window: params.window, swing: params.swing, fit: params.fit } })).data,
    enabled, staleTime: 5 * 60_000, retry: false,
  })
}

const errorDetail = (error: unknown) => (error as { response?: { status?: number; data?: { detail?: string } } }).response
const samePreset = (a: Omit<StructureParams, 'code' | 'market'>, b: StructureParams) => a.kind === b.kind && a.window === b.window && a.swing === b.swing && a.fit === b.fit

export function StructurePresetChips({ params, onPick }: { params: StructureParams; onPick: (preset: Omit<StructureParams, 'code' | 'market'>) => void }) {
  return <div className="flex flex-wrap items-center gap-1.5" aria-label="추천 구조">
    <span className="text-caption text-muted-foreground">바로 그리기</span>
    {STRUCTURE_PRESETS.map(preset => <Button key={preset.id} size="sm" variant={samePreset(preset.params, params) ? 'secondary' : 'outline'} className="h-7 px-2.5 text-caption" title={preset.purpose} onClick={() => onPick(preset.params)}>{preset.label}</Button>)}
  </div>
}

/** 종목 하나의 차트·요약·후속 행동. 컨트롤은 상위 카드가 공유한다. */
function StructureChart({ params, onChange, height, compact }: { params: StructureParams; onChange: (next: StructureParams) => void; height: number; compact: boolean }) {
  const id = useId()
  const query = useChartStructure(params)
  const result = query.data
  const [conditionId, setConditionId] = useState<string | null>(null)
  const appendRule = useAppendMemberRule()
  const price = (value: number) => params.market === 'us' ? formatPrice(value) : `${formatNumber(Math.round(value))}원`
  const overlays = (result?.lines ?? []).map((line, index) => ({ id: line.id, title: line.label, token: `--chart-${(index % 3) + 3}`, data: line.points, dashed: true }))
  const markers = (result?.pivots ?? []).map(p => ({ time: p.time, text: p.anchor ? '기준점' : '스윙', direction: (p.side === 'high' ? 'down' : 'up') as 'up' | 'down' })) // 고점은 봉 위, 저점은 봉 아래
  const failure = query.isError ? errorDetail(query.error) : null
  const condition = result?.conditions.find(c => c.strategy_id === conditionId) ?? result?.conditions[0]
  const searchQuestion = condition ? `다음 조건을 모두 만족하는 종목을 찾아줘.\n- ${condition.phrase}` : ''
  async function watch(groupId: number) {
    if (!condition) return
    try {
      await appendRule.mutateAsync({ groupId, stockCode: params.code, rule: { strategy_id: condition.strategy_id, params: condition.params, within_days: condition.within_days } })
      toast.success(`${result?.name ?? params.code}의 감시 규칙에 '${condition.label}'을 추가했습니다.`, { description: '매일 16:40 평가 뒤 관심 종목 신호 화면에 나타납니다.' })
    } catch (error) { toast.error('감시 규칙을 추가하지 못했습니다.', { description: (error as Error).message }) }
  }
  return <div className="space-y-3">
    {query.isPending && <div className="space-y-2" role="status" aria-label="구조 계산 중"><Skeleton className="w-full" style={{ height }} /><p className="text-caption text-muted-foreground">스윙 점을 찾고 있습니다.</p></div>}
    {query.isError && (failure?.status === 422
      ? <div className="space-y-2 rounded-lg bg-muted/40 p-3"><p className="text-sm">{failure.data?.detail ?? '구조를 그릴 수 없습니다.'}</p><div className="flex flex-wrap gap-2">
        {params.swing > 2 && <Button size="sm" variant="outline" onClick={() => onChange({ ...params, swing: Math.max(2, Math.floor(params.swing / 2)) })}>스윙 폭 줄이기</Button>}
        {params.window !== '2y' && <Button size="sm" variant="outline" onClick={() => onChange({ ...params, window: params.window === 'ytd' || params.window === '3m' || params.window === '6m' ? '1y' : '2y' })}>기간 늘리기</Button>}</div></div>
      : <ErrorState message={failure?.status === 404 ? (failure.data?.detail ?? '저장된 시세가 없는 종목입니다.') : '구조를 계산하지 못했습니다.'} onRetry={() => query.refetch()} />)}
    {result && <>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-medium">{result.name} <span className="text-caption font-normal text-muted-foreground">{result.code}</span></h4>
        {result.notes.length > 0 && <div className="flex flex-wrap gap-1.5">{result.notes.map(note => <Badge key={note} variant="secondary" className="font-normal">{note}</Badge>)}</div>}
      </div>
      <CandlestickChart data={result.candles} overlays={overlays} markers={markers} height={height} initialRange={{ from: result.candles[0]?.time, to: result.candles.at(-1)?.time ?? '' }} formatValue={value => params.market === 'us' ? formatPrice(value) : formatNumber(Math.round(value))} />
      <p className="text-sm">
        {result.kind === 'channel' && <>상단 {price(result.summary.upper_now ?? 0)} · 하단 {price(result.summary.lower_now ?? 0)} · 종가 {price(result.summary.close)} → 채널 안 위치 {result.summary.position_pct == null ? '-' : `${formatNumber(Math.round(result.summary.position_pct))}%`}{result.summary.position_pct != null && result.summary.position_pct > 100 ? ' (상단 위)' : result.summary.position_pct != null && result.summary.position_pct < 0 ? ' (하단 아래)' : ''} · 접촉 상단 {formatNumber(result.summary.touches_upper ?? 0)}회 / 하단 {formatNumber(result.summary.touches_lower ?? 0)}회</>}
        {(result.kind === 'trendline_high' || result.kind === 'trendline_low') && <>추세선 {price(result.summary.line_now ?? 0)} · 종가 {price(result.summary.close)} ({formatPercent(result.summary.distance_pct)}) · 접촉 {formatNumber(result.summary.touches ?? 0)}회</>}
        {result.kind === 'levels' && <>종가 {price(result.summary.close)} · 가까운 저항 {result.summary.nearest_resistance != null ? `${price(result.summary.nearest_resistance)} (${formatPercent(result.summary.resistance_distance_pct)} 위)` : '없음'} · 가까운 지지 {result.summary.nearest_support != null ? `${price(result.summary.nearest_support)} (${formatPercent(result.summary.support_distance_pct)} 아래)` : '없음'} · 레벨 {formatNumber(result.summary.levels?.length ?? 0)}개</>}
        {result.summary.slope_pct_per_session != null && <> · 기울기 세션당 {formatPercent(result.summary.slope_pct_per_session)}</>}
      </p>
      {result.kind === 'levels' && result.summary.levels && result.summary.levels.length > 0 && <ul className="flex flex-wrap gap-1.5">{[...result.summary.levels].sort((a, b) => b.price - a.price).map(level => <li key={level.price}><Badge variant={level.role === 'resistance' ? 'default' : 'secondary'} className="font-normal tabular-nums">{level.role === 'resistance' ? '저항' : '지지'} {price(level.price)} · {formatNumber(level.touches)}회</Badge></li>)}</ul>}
      <p className="text-caption text-muted-foreground">{result.window.from} ~ {result.window.to} · {formatNumber(result.window.sessions)}거래일 · 기준점 {formatNumber(result.pivots.filter(p => p.anchor).length)}개 / 스윙 {formatNumber(result.pivots.length)}개. 구조는 규칙(스윙 폭·적합 방식)으로 그린 결정적 선이고 예측이 아닙니다.</p>
      {result.conditions.length > 0 && <div className="flex flex-wrap items-end gap-2 rounded-lg bg-muted/40 p-3" aria-label="이 구조를 조건으로">
        <div className="space-y-1"><Label htmlFor={`${id}-condition`} className="text-caption text-muted-foreground">이 구조를 조건으로</Label>
          <Select value={condition?.strategy_id} onValueChange={setConditionId}><SelectTrigger id={`${id}-condition`} size="sm" className="h-8 w-auto min-w-44"><SelectValue /></SelectTrigger>
            <SelectContent>{result.conditions.map(item => <SelectItem key={item.strategy_id} value={item.strategy_id}>{item.label}</SelectItem>)}</SelectContent></Select></div>
        {params.market === 'kr' && <GroupPicker label={appendRule.isPending ? '추가 중…' : '감시 규칙으로'} icon={<Bell className="size-3.5" />} onPick={watch} busy={appendRule.isPending} />}
        <Button asChild variant="outline" size="sm"><Link to={`/discover?q=${encodeURIComponent(searchQuestion)}`}><Search className="size-3.5" />이 조건으로 종목 찾기</Link></Button>
        {!compact && <Button asChild variant="ghost" size="sm"><Link to={params.market === 'us' ? `/us/${params.code}` : `/analyze/${params.code}/summary`}><ExternalLink className="size-3.5" />기업 페이지</Link></Button>}
        <p className="basis-full text-caption text-muted-foreground">{condition?.note}</p>
      </div>}
    </>}
  </div>
}

export function ChartStructureCard({ params, codes, onChange, question, height = 360, compact = false }: {
  params: StructureParams; codes?: string[]; onChange: (next: StructureParams) => void; question?: string; height?: number; compact?: boolean
}) {
  const id = useId()
  const [swingDraft, setSwingDraft] = useState<number | null>(null) // 드래그 중 표시값. 계산은 놓을 때(onValueCommit)만
  const targets = codes && codes.length > 0 ? codes : [params.code]
  const isLevels = params.kind === 'levels'
  return <section aria-label="차트 구조 그리기" className={compact ? 'space-y-3' : 'space-y-4 rounded-xl border bg-card p-4'}>
    {!compact && <div className="space-y-1">
      {question && <p className="text-sm text-muted-foreground">{question}</p>}
      <h3 className="text-base font-semibold">{targets.length > 1 ? `${formatNumber(targets.length)}종목 비교` : params.code} · {WINDOW_LABEL[params.window] ?? params.window} {KIND_LABEL[params.kind]}</h3>
    </div>}
    <StructurePresetChips params={params} onPick={preset => onChange({ ...params, ...preset })} />
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-1"><Label className="text-caption text-muted-foreground">구조</Label>
        <ToggleGroup type="single" variant="outline" size="sm" value={params.kind} onValueChange={value => { if (value) onChange({ ...params, kind: value as StructureKind }) }} aria-label="구조 종류">
          {(Object.keys(KIND_LABEL) as StructureKind[]).map(kind => <ToggleGroupItem key={kind} value={kind} className="h-8 px-3 text-sm">{KIND_LABEL[kind]}</ToggleGroupItem>)}
        </ToggleGroup></div>
      <div className="space-y-1"><Label htmlFor={`${id}-window`} className="text-caption text-muted-foreground">기간</Label>
        <Select value={params.window in WINDOW_LABEL ? params.window : 'custom'} onValueChange={value => { if (value !== 'custom') onChange({ ...params, window: value }) }}>
          <SelectTrigger id={`${id}-window`} size="sm" className="h-8 w-28"><SelectValue /></SelectTrigger>
          <SelectContent>{Object.entries(WINDOW_LABEL).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}{!(params.window in WINDOW_LABEL) && <SelectItem value="custom">{params.window}</SelectItem>}</SelectContent>
        </Select></div>
      <div className="min-w-44 space-y-1"><Label htmlFor={`${id}-swing`} className="text-caption text-muted-foreground">스윙 폭 {swingDraft ?? params.swing}봉 {(swingDraft ?? params.swing) >= 10 ? '(큰 구조)' : (swingDraft ?? params.swing) <= 3 ? '(세밀)' : ''}</Label>
        <Slider id={`${id}-swing`} min={2} max={30} step={1} value={[swingDraft ?? params.swing]} onValueChange={([value]) => setSwingDraft(value)} onValueCommit={([value]) => { setSwingDraft(null); onChange({ ...params, swing: value }) }} aria-label="스윙 폭" /></div>
      {!isLevels && <div className="space-y-1"><Label className="text-caption text-muted-foreground">적합</Label>
        <ToggleGroup type="single" variant="outline" size="sm" value={params.fit} onValueChange={value => { if (value) onChange({ ...params, fit: value as StructureFit }) }} aria-label="적합 방식">
          <ToggleGroupItem value="two_point" className="h-8 px-3 text-sm">두 점 연결</ToggleGroupItem><ToggleGroupItem value="regression" className="h-8 px-3 text-sm">회귀선</ToggleGroupItem>
        </ToggleGroup></div>}
    </div>
    <div className={targets.length > 1 ? 'grid grid-cols-1 gap-4 xl:grid-cols-2' : ''}>
      {targets.map(code => <StructureChart key={code} params={{ ...params, code }} onChange={next => onChange({ ...next, code: params.code })} height={targets.length > 1 ? Math.min(height, 300) : height} compact={compact} />)}
    </div>
  </section>
}
