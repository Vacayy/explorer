import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import api from '@/api/client'
import CandlestickChart from '@/components/charts/CandlestickChart'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Slider } from '@/components/ui/slider'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ErrorState } from '@/components/shared/ErrorState'
import { formatNumber, formatPercent, formatPrice } from '@/utils/format'

/** 종목 하나의 차트에 채널·추세선을 그리는 결정적 계산 (docs/specs/chart-structure.md, D-195). 모델 호출 0. */
export type StructureKind = 'channel' | 'trendline_high' | 'trendline_low'
export type StructureFit = 'two_point' | 'regression'
export interface StructureParams { code: string; market: 'kr' | 'us'; kind: StructureKind; window: string; swing: number; fit: StructureFit }
export interface StructureResult {
  code: string; name: string; market: 'kr' | 'us'; kind: StructureKind; fit: StructureFit; swing: number; requested_swing: number
  window: { from: string; to: string; requested_from: string; sessions: number }
  candles: { time: string; open: number; high: number; low: number; close: number }[]
  pivots: { time: string; price: number; side: 'high' | 'low'; anchor: boolean }[]
  lines: { id: string; label: string; points: { time: string; value: number }[] }[]
  summary: { upper_now?: number; lower_now?: number; line_now?: number; close: number; position_pct?: number | null; width_pct?: number | null; distance_pct?: number | null; touches_upper?: number; touches_lower?: number; touches?: number; slope_pct_per_session: number | null; sessions: number }
  notes: string[]
}

export const KIND_LABEL: Record<StructureKind, string> = { channel: '채널', trendline_high: '고점 추세선', trendline_low: '저점 추세선' }
export const WINDOW_LABEL: Record<string, string> = { ytd: '올해', '3m': '3개월', '6m': '6개월', '1y': '1년', '2y': '2년' }

export function useChartStructure(params: StructureParams, enabled = true) {
  return useQuery({
    queryKey: ['spine', 'chart-structure', params],
    queryFn: async () => (await api.get<StructureResult>(`/api/spine/chart-structure/${params.code}`, { params: { market: params.market, kind: params.kind, window: params.window, swing: params.swing, fit: params.fit } })).data,
    enabled, staleTime: 5 * 60_000, retry: false,
  })
}

const errorDetail = (error: unknown) => (error as { response?: { status?: number; data?: { detail?: string } } }).response

export function ChartStructureCard({ params, onChange, question, height = 360, compact = false }: {
  params: StructureParams; onChange: (next: StructureParams) => void; question?: string; height?: number; compact?: boolean
}) {
  const id = useId()
  const [swingDraft, setSwingDraft] = useState<number | null>(null) // 드래그 중 표시값. 계산은 놓을 때(onValueCommit)만
  const query = useChartStructure(params)
  const result = query.data
  const price = (value: number) => params.market === 'us' ? formatPrice(value) : `${formatNumber(Math.round(value))}원`
  const overlays = (result?.lines ?? []).map((line, index) => ({ id: line.id, title: line.label, token: `--chart-${(index % 3) + 3}`, data: line.points, dashed: true }))
  const markers = (result?.pivots ?? []).map(p => ({ time: p.time, text: p.anchor ? '기준점' : '스윙', direction: (p.side === 'high' ? 'down' : 'up') as 'up' | 'down' })) // 고점은 봉 위(아래 화살표), 저점은 봉 아래
  const failure = query.isError ? errorDetail(query.error) : null
  return <section aria-label="차트 구조 그리기" className={compact ? 'space-y-3' : 'space-y-4 rounded-xl border bg-card p-4'}>
    {!compact && <div className="space-y-1">
      {question && <p className="text-sm text-muted-foreground">{question}</p>}
      <h3 className="text-base font-semibold">{result?.name ?? params.code} · {WINDOW_LABEL[params.window] ?? params.window} {KIND_LABEL[params.kind]}</h3>
    </div>}
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
      <div className="space-y-1"><Label className="text-caption text-muted-foreground">적합</Label>
        <ToggleGroup type="single" variant="outline" size="sm" value={params.fit} onValueChange={value => { if (value) onChange({ ...params, fit: value as StructureFit }) }} aria-label="적합 방식">
          <ToggleGroupItem value="two_point" className="h-8 px-3 text-sm">두 점 연결</ToggleGroupItem><ToggleGroupItem value="regression" className="h-8 px-3 text-sm">회귀선</ToggleGroupItem>
        </ToggleGroup></div>
    </div>
    {query.isPending && <div className="space-y-2" role="status" aria-label="구조 계산 중"><Skeleton className="w-full" style={{ height }} /><p className="text-caption text-muted-foreground">스윙 점을 찾고 있습니다.</p></div>}
    {query.isError && (failure?.status === 422
      ? <div className="space-y-2 rounded-lg bg-muted/40 p-3"><p className="text-sm">{failure.data?.detail ?? '구조를 그릴 수 없습니다.'}</p><div className="flex flex-wrap gap-2">
        {params.swing > 2 && <Button size="sm" variant="outline" onClick={() => onChange({ ...params, swing: Math.max(2, Math.floor(params.swing / 2)) })}>스윙 폭 줄이기</Button>}
        {params.window !== '2y' && <Button size="sm" variant="outline" onClick={() => onChange({ ...params, window: params.window === 'ytd' || params.window === '3m' || params.window === '6m' ? '1y' : '2y' })}>기간 늘리기</Button>}</div></div>
      : <ErrorState message={failure?.status === 404 ? (failure.data?.detail ?? '저장된 시세가 없는 종목입니다.') : '구조를 계산하지 못했습니다.'} onRetry={() => query.refetch()} />)}
    {result && <>
      {result.notes.length > 0 && <div className="flex flex-wrap gap-1.5">{result.notes.map(note => <Badge key={note} variant="secondary" className="font-normal">{note}</Badge>)}</div>}
      <CandlestickChart data={result.candles} overlays={overlays} markers={markers} height={height} initialRange={{ from: result.candles[0]?.time, to: result.candles.at(-1)?.time ?? '' }} formatValue={value => params.market === 'us' ? formatPrice(value) : formatNumber(Math.round(value))} />
      <p className="text-sm">
        {result.kind === 'channel'
          ? <>상단 {price(result.summary.upper_now ?? 0)} · 하단 {price(result.summary.lower_now ?? 0)} · 종가 {price(result.summary.close)} → 채널 안 위치 {result.summary.position_pct == null ? '-' : `${formatNumber(Math.round(result.summary.position_pct))}%`}{result.summary.position_pct != null && result.summary.position_pct > 100 ? ' (상단 위)' : result.summary.position_pct != null && result.summary.position_pct < 0 ? ' (하단 아래)' : ''} · 접촉 상단 {formatNumber(result.summary.touches_upper ?? 0)}회 / 하단 {formatNumber(result.summary.touches_lower ?? 0)}회</>
          : <>추세선 {price(result.summary.line_now ?? 0)} · 종가 {price(result.summary.close)} ({formatPercent(result.summary.distance_pct)}) · 접촉 {formatNumber(result.summary.touches ?? 0)}회</>}
        {result.summary.slope_pct_per_session != null && <> · 기울기 세션당 {formatPercent(result.summary.slope_pct_per_session)}</>}
      </p>
      <p className="text-caption text-muted-foreground">{result.window.from} ~ {result.window.to} · {formatNumber(result.window.sessions)}거래일 · 기준점 {formatNumber(result.pivots.filter(p => p.anchor).length)}개 / 스윙 {formatNumber(result.pivots.length)}개. 구조는 규칙(스윙 폭·적합 방식)으로 그린 결정적 선이고 예측이 아닙니다.</p>
      {!compact && <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm"><Link to={params.market === 'us' ? `/us/${params.code}` : `/analyze/${params.code}/summary`}><ExternalLink className="size-3.5" />기업 페이지에서 보기</Link></Button>
      </div>}
    </>}
  </section>
}
