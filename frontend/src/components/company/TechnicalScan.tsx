import { useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChartCandlestick, ChevronDown, RefreshCw, Sparkles, X } from 'lucide-react'
import api from '@/api/client'
import type { ChartMarker } from '@/components/charts/CandlestickChart'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ErrorState } from '@/components/shared/ErrorState'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import { ChartStructureCard, KIND_LABEL, WINDOW_LABEL, type StructureKind, type StructureParams } from '@/components/structure/ChartStructureCard'
import { PenLine } from 'lucide-react'
import { technicalHighlights } from '@/components/company/scanEvidence'
import { evidenceValue, EXCLUSION_LABELS } from '@/components/analysis/strategyEvidence'
import { TechnicalEvidence } from '@/components/company/TechnicalEvidence'

/** 기업 페이지 차트의 '기술적 분석': 카탈로그 전략 51개를 이 종목 시세에 전부 돌린 결과. D-190. */
export interface ScanEntry { id: string; label: string; category: string; status: 'pass' | 'fail' | 'unavailable'; date: string | null; value: number | null; reference: number | null; reason: string | null; within_days: number }
export interface TechnicalScanResult {
  code: string; market: 'kr' | 'us'; as_of: string | null; within: number; sessions: number
  signals: ScanEntry[]; states: ScanEntry[]; unavailable: ScanEntry[]
  counts: { evaluated: number; passed: number; failed: number; unavailable: number }
  markers: { time: string; label: string; kind: 'signal' | 'pivot'; price?: number | null }[]
  lines: { id: string; label: string; points: { time: string; value: number }[] }[]
  /** 한 줄 읽기(D-198): 계열 5개 질문마다 판정 값을 채운 평서문. basis는 값을 준 조건 id(또는 price.*). */
  readings: { group: string; question: string; text: string; basis: string[] }[]
  /** 자동 캔버스(D-198): 스캔 결과로 고른 '먼저 그릴 구조'. */
  canvas: { kind: StructureKind; window: string; swing: number; fit: 'two_point' | 'regression'; reason: string; basis: string[] } | null
}

/** AI 해설(D-191): 모델은 차트가 아니라 위 스캔 결과만 읽고, 문장마다 근거 id를 붙인다. 근거 없는 문장은 서버가 버린다. */
export interface CommentaryPoint { text: string; basis: string[] }
export interface TechnicalCommentary {
  id: number; created_at: string; model: string | null; cost_usd: number | null; as_of: string; within: number; reused: boolean
  summary: string; reading: CommentaryPoint[]; caveats: string[]; watch: CommentaryPoint[]
  basis_labels: Record<string, string>; dropped_unsupported: number
}

const PRICE_LABEL: Record<string, string> = { 'price.close': '기준일 종가', 'price.ret_20d': '20거래일 수익률', 'price.ret_60d': '60거래일 수익률', 'price.ret_120d': '120거래일 수익률', 'price.from_52w_high_pct': '52주 고점 대비', 'price.from_52w_low_pct': '52주 저점 대비', 'price.volume_vs_20d_avg': '거래량 / 20일 평균', 'price.sessions': '시세 기간', 'price.as_of': '기준일' }

export function useTechnicalScan(code: string, market: 'kr' | 'us', within: number, enabled: boolean) {
  return useQuery({
    queryKey: ['spine', 'technical-scan', market, code, within],
    queryFn: async () => (await api.get<TechnicalScanResult>(`/api/spine/technical-scan/${code}`, { params: { market, within } })).data,
    enabled, staleTime: 5 * 60_000,
  })
}

// 드물고 방향이 분명한 조건만 '특이점'으로 앞세운다. 갭·5일선 교차처럼 잦은 것은 뒤로.
const NOTABLE = new Set(['high_52w', 'low_52w', 'high_ytd', 'low_ytd', 'golden_cross_20_60', 'dead_cross_20_60', 'trend_reversal_confirmed', 'macd_zero_cross', 'breakout_pullback_10d', 'volume_profile_up_60d', 'volume_profile_down_60d', 'rsi_exit_oversold', 'rsi_exit_overbought', 'bollinger_reenter_lower', 'bollinger_reenter_upper', 'adx_rise_above'])
const UP = /(상향|신고가|골든|매수|상승|지지|재돌파)/
const DOWN = /(하향|신저가|데드|이탈|하락)/
const GROUP_LABEL: Record<string, string> = { '가격 구조': '구조 (스윙·추세선·채널)', 시세동향: '가격·거래량', 지표신호: '이동평균·지표', '추세·모멘텀': '추세·모멘텀 (수익률·ADX·장기 이평)', 평균회귀: '평균회귀 (이격·RSI·볼린저)' }
// 계열이 시장을 읽는 핵심 질문(D-197). 상태 배지를 이 질문 아래 묶어 '무엇을 말하는 상태인지'를 먼저 보인다.
const GROUP_QUESTION: Record<string, string> = { '가격 구조': '주요 가격대에서 어떻게 반응하는가', 시세동향: '가격·거래량이 극값인가', 지표신호: '이동평균·지표가 어디에 있는가', '추세·모멘텀': '나타난 방향성이 이어지고 있는가', 평균회귀: '기준에서 얼마나 멀어졌는가' }

export function isNotable(entry: { id: string; category: string }) { return entry.category === '가격 구조' || NOTABLE.has(entry.id) }

/** 차트에는 특이점과 스윙 점만 올린다. 잦은 신호(갭·5일선 교차 등)는 겹쳐서 읽을 수 없으므로 패널 목록에만 둔다. */
export function scanToChart(scan: TechnicalScanResult | undefined) {
  if (!scan) return { markers: [] as ChartMarker[], overlays: [] as { id: string; title: string; token: string; data: { time: string; value: number }[]; dashed?: boolean }[] }
  const notableLabels = new Set(scan.signals.filter(isNotable).map(s => s.label))
  const markers: ChartMarker[] = scan.markers.filter(m => m.kind === 'pivot' || notableLabels.has(m.label)).map(m => ({ time: m.time, text: m.label, direction: m.kind === 'pivot' ? 'down' : DOWN.test(m.label) && !UP.test(m.label) ? 'down' : 'up' }))
  const overlays = scan.lines.map((line, index) => ({ id: line.id, title: line.label, token: `--chart-${(index % 3) + 3}`, data: line.points, dashed: true }))
  return { markers, overlays }
}

function Commentary({ code, market, within, enabled }: { code: string; market: 'kr' | 'us'; within: number; enabled: boolean }) {
  const client = useQueryClient()
  const key = ['spine', 'technical-commentary', market, code, within]
  const stored = useQuery({
    queryKey: key, enabled, staleTime: 5 * 60_000, retry: false,
    queryFn: async () => {
      try { return (await api.get<TechnicalCommentary>(`/api/spine/technical-scan/${code}/commentary`, { params: { market, within } })).data }
      catch (error) { if ((error as { response?: { status?: number } }).response?.status === 404) return null; throw error }
    },
  })
  const generate = useMutation({
    mutationFn: async (force: boolean) => (await api.post<TechnicalCommentary>(`/api/spine/technical-scan/${code}/commentary`, null, { params: { market, within, force } })).data,
    onSuccess: data => client.setQueryData(key, data),
  })
  const commentary = stored.data ?? null
  const basisLabel = (id: string) => commentary?.basis_labels[id] ?? PRICE_LABEL[id] ?? id
  const errorMessage = (error: unknown) => (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'AI 해설을 만들지 못했습니다.'
  return <div className="space-y-2 rounded-lg bg-muted/40 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="flex items-center gap-1.5 text-caption font-medium text-muted-foreground"><Sparkles className="size-3.5" />AI 해설<span className="font-normal">· 위 판정만 읽은 모델 의견(가설)</span></h4>
      {commentary && <div className="flex items-center gap-2 text-caption text-muted-foreground"><span>{formatRelativeTime(commentary.created_at)}</span>
        <Button variant="ghost" size="sm" className="h-6 px-1.5 text-caption" disabled={generate.isPending} onClick={() => generate.mutate(true)} aria-label="AI 해설 다시 만들기"><RefreshCw className={`size-3 ${generate.isPending ? 'animate-spin' : ''}`} />다시 만들기</Button></div>}
    </div>
    {generate.isPending && <div className="space-y-2" role="status" aria-label="해설 생성 중"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" /><Skeleton className="h-4 w-2/3" /><p className="text-caption text-muted-foreground">모델이 판정 결과를 읽고 있습니다. 보통 20~40초.</p></div>}
    {!generate.isPending && generate.isError && <ErrorState message={errorMessage(generate.error)} onRetry={() => generate.mutate(false)} />}
    {!generate.isPending && !generate.isError && !commentary && <div className="flex flex-wrap items-center gap-3">
      <p className="text-sm text-muted-foreground">성립한 조건·상태·가격 위치를 모델이 서로 연결해 읽어줍니다. 문장마다 근거 조건이 붙고, 예측·추천은 하지 않습니다.</p>
      <Button size="sm" variant="outline" disabled={stored.isPending} onClick={() => generate.mutate(false)}><Sparkles className="size-3.5" />AI 해설 만들기</Button></div>}
    {!generate.isPending && commentary && <div className="space-y-3">
      <p className="text-sm">{commentary.summary}</p>
      {commentary.reading.length > 0 && <ul className="space-y-1.5">{commentary.reading.map((point, index) => <li key={index} className="text-sm"><span>{point.text}</span><span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">{point.basis.map(id => <Badge key={id} variant="outline" className="h-5 px-1.5 text-[11px] font-normal text-muted-foreground">{basisLabel(id)}</Badge>)}</span></li>)}</ul>}
      {commentary.watch.length > 0 && <div className="space-y-1"><p className="text-caption font-medium text-muted-foreground">이 읽기가 바뀌는지 볼 것</p><ul className="space-y-1">{commentary.watch.map((point, index) => <li key={index} className="text-sm"><span>{point.text}</span><span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">{point.basis.map(id => <Badge key={id} variant="outline" className="h-5 px-1.5 text-[11px] font-normal text-muted-foreground">{basisLabel(id)}</Badge>)}</span></li>)}</ul></div>}
      {commentary.caveats.length > 0 && <p className="text-caption text-muted-foreground">보지 않은 것: {commentary.caveats.join(' · ')}</p>}
      <p className="text-caption text-muted-foreground">{commentary.as_of} 기준 · 최근 {commentary.within}거래일 판정을 읽음{commentary.dropped_unsupported > 0 && ` · 근거 없는 문장 ${formatNumber(commentary.dropped_unsupported)}개 제외`}. 매수·매도 판단이 아닙니다.</p>
    </div>}
  </div>
}

export function TechnicalScan({ code, market, within, onWithin, onChart, onToggleChart, onClose, chart }: {
  chart?: ReactNode; code: string; market: 'kr' | 'us'; within: number; onWithin: (value: number) => void; onChart: boolean; onToggleChart: (value: boolean) => void; onClose: () => void
}) {
  const query = useTechnicalScan(code, market, within, true)
  const scan = query.data
  const notable = useMemo(() => (scan?.signals ?? []).filter(isNotable), [scan])
  const rest = useMemo(() => (scan?.signals ?? []).filter(s => !isNotable(s)), [scan])
  const grouped = useMemo(() => { const map = new Map<string, ScanEntry[]>(); for (const s of rest) map.set(s.category, [...(map.get(s.category) ?? []), s]); return [...map.entries()] }, [rest])
  const activeStates = scan?.states.filter(s => s.status === 'pass') ?? []
  const [params, setParams] = useSearchParams()
  const view = params.get('scan_view') === 'structure' ? 'structure' : 'reading'
  const [commentaryOpen, setCommentaryOpen] = useState(false)
  const canvas = scan?.canvas ?? null
  const defaults = canvas ?? { kind: 'levels' as const, window: '1y', swing: 5, fit: 'two_point' as const }
  const kind = params.get('structure_kind')
  const window = params.get('structure_window')
  const swing = Number(params.get('structure_swing'))
  const fit = params.get('structure_fit')
  const structure: StructureParams = { code, market,
    kind: kind && Object.keys(KIND_LABEL).includes(kind) ? kind as StructureKind : defaults.kind,
    window: window && Object.keys(WINDOW_LABEL).includes(window) ? window : defaults.window,
    swing: Number.isInteger(swing) && swing >= 2 && swing <= 30 ? swing : defaults.swing,
    fit: fit === 'two_point' || fit === 'regression' ? fit : defaults.fit,
  }
  const customStructure = ['structure_kind', 'structure_window', 'structure_swing', 'structure_fit'].some(key => params.has(key))
  const changeStructure = (value: StructureParams) => setParams(previous => {
    const next = new URLSearchParams(previous)
    next.set('structure_kind', value.kind); next.set('structure_window', value.window)
    next.set('structure_swing', String(value.swing)); next.set('structure_fit', value.fit)
    return next
  }, { replace: true, preventScrollReset: true })
  const latestSignal = [...notable].sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))[0]
  const entries = scan ? [...scan.states, ...scan.signals, ...scan.unavailable] : []
  return <section aria-label="기술적 분석" className="space-y-4 rounded-xl border p-3 sm:p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">기술적 분석</h3>
        {scan && <span className="text-caption text-muted-foreground">시세 {scan.as_of} 기준 · {formatNumber(scan.sessions)}거래일 자료</span>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {view === 'reading' && <><div className="flex flex-wrap items-center gap-1.5"><Label htmlFor="scan-within" className="text-caption text-muted-foreground">신호가 발생한 기간</Label>
          <Select value={String(within)} onValueChange={value => onWithin(Number(value))}><SelectTrigger id="scan-within" className="min-h-11 w-auto min-w-28" aria-label="신호가 발생한 기간"><SelectValue /></SelectTrigger><SelectContent>{[1, 3, 5, 10, 20].map(n => <SelectItem key={n} value={String(n)}>{n === 1 ? '기준일 당일' : `최근 ${n}거래일`}</SelectItem>)}</SelectContent></Select></div>
        <label className="flex items-center gap-1.5 text-caption text-muted-foreground"><Switch checked={onChart} onCheckedChange={onToggleChart} aria-label="차트에 표시" />차트에 표시</label></>}
        <Button variant="ghost" size="icon-sm" className="size-11" aria-label="기술적 분석 닫기" onClick={onClose}><X className="size-4" /></Button>
      </div>
    </div>
    {query.isPending && <div className="space-y-2" role="status" aria-label="분석 중"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /><Skeleton className="h-4 w-3/5" /></div>}
    {query.isError && <ErrorState message="기술적 분석을 계산하지 못했습니다." onRetry={() => query.refetch()} />}
    <Tabs value={view} onValueChange={value => setParams(previous => { const next = new URLSearchParams(previous); next.set('scan_view', value); return next }, { replace: true, preventScrollReset: true })} className="min-w-0 flex-col gap-4">
      <TabsList aria-label="기술적 분석 보기" className="grid w-full grid-cols-2 rounded-xl group-data-horizontal/tabs:h-auto p-1 sm:w-fit"><TabsTrigger value="reading" className="min-h-11 min-w-0 gap-1 rounded-lg px-2 text-caption sm:gap-2 sm:px-3 sm:text-sm data-[state=active]:bg-background data-[state=active]:text-primary data-[state=active]:shadow-sm"><ChartCandlestick className="size-4" />차트 읽기</TabsTrigger><TabsTrigger value="structure" className="min-h-11 min-w-0 gap-1 rounded-lg px-2 text-caption sm:gap-2 sm:px-3 sm:text-sm data-[state=active]:bg-background data-[state=active]:text-primary data-[state=active]:shadow-sm"><PenLine className="size-4" />구조 그리기</TabsTrigger></TabsList>
      <TabsContent value="reading" className="min-w-0 space-y-4">
    <div className={chart ? 'grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]' : ''}>
      {chart && <div className="min-w-0 space-y-2" aria-label="분석 가격 차트">{chart}</div>}
      {scan && <section aria-label="핵심 관측 세 가지" className="min-w-0 space-y-3"><h4 className="text-sm font-medium">지금 차트에서 확인할 것</h4><ol className="divide-y rounded-lg bg-muted/30 px-3">{technicalHighlights(scan.readings).map((reading, index) => <li key={reading.group} className="space-y-2 py-3"><h5 className="text-caption font-medium text-muted-foreground">0{index + 1} · {reading.title}</h5><p className="text-sm leading-relaxed">{reading.text}</p>{reading.ids.length > 0 && <TechnicalEvidence ids={reading.ids} entries={entries} asOf={scan.as_of} priceLabels={PRICE_LABEL} />}</li>)}</ol><p className="text-caption text-muted-foreground">{scan.as_of} 시세의 관측입니다. 전체 지표와 최근 신호는 아래에서 확인하세요.</p></section>}
    </div>
      {scan && <section aria-label="다음 확인" className="space-y-2 rounded-lg border p-3"><h4 className="text-sm font-medium">다음 확인</h4>{latestSignal ? <><p className="text-sm">최근 확인한 변화: {latestSignal.label} · {latestSignal.date ?? '날짜 미확인'}. 다음 시세에서 이 신호 이후의 가격 변화와 거래량을 함께 확인하세요.</p><TechnicalEvidence ids={[latestSignal.id]} entries={entries} asOf={scan.as_of} priceLabels={PRICE_LABEL} /></> : <p className="text-sm text-muted-foreground">계산 가능한 조건에서 최근 {within}거래일의 주요 변화는 확인되지 않았습니다. 다음 시세에서 이동평균 대비 위치와 거래량 변화를 확인하세요.</p>}</section>}
      </TabsContent>
      <TabsContent value="structure" className="min-w-0 space-y-4">
        <div className="space-y-1"><h4 className="text-sm font-semibold">채널·추세선·지지와 저항을 직접 살펴보세요</h4><p className="text-caption text-muted-foreground">기간과 구조를 바꾸며 현재 가격의 위치를 확인합니다. 여기서 그리는 선은 신호 판정선과 별도로 계산합니다.</p>{canvas && !customStructure && <p className="text-caption text-muted-foreground">현재 관측에서 먼저 살펴볼 구조: {WINDOW_LABEL[canvas.window] ?? canvas.window} {KIND_LABEL[canvas.kind]}</p>}</div>
        {query.isPending && !customStructure ? <Skeleton className="h-80 w-full" aria-label="첫 구조 준비 중" /> : <ChartStructureCard compact params={structure} onChange={changeStructure} height={360} />}
      </TabsContent>
    </Tabs>
    {scan && <>
      <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" className="min-h-11 h-auto w-full justify-between whitespace-normal text-left">전체 지표·최근 신호와 계산 근거<ChevronDown className="size-4 shrink-0" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-4 pt-3">
      {scan.readings?.length > 0 && <div className="space-y-2" aria-label="한 줄 읽기">
        <h4 className="text-caption font-medium text-muted-foreground">한 줄 읽기 · {scan.as_of} · 판정 값을 문장으로 옮긴 것이고 예측이 아닙니다</h4>
        <ul className="divide-y">{scan.readings.map(reading => <li key={reading.group} className="space-y-1 py-2 first:pt-0 last:pb-0">
          <p className="text-caption text-muted-foreground" title={GROUP_LABEL[reading.group]}>{reading.question ?? GROUP_QUESTION[reading.group]}</p>
          <p className="text-sm">{reading.text}</p>
          <TechnicalEvidence ids={[...reading.basis, ...activeStates.filter(s => s.category === reading.group && !reading.basis.includes(s.id)).map(s => s.id)]} entries={entries} asOf={scan.as_of} priceLabels={PRICE_LABEL} />
        </li>)}</ul>
      </div>}
      <div className="space-y-2">
        <h4 className="text-caption font-medium text-muted-foreground">특이점</h4>
        {notable.length === 0 ? <p className="text-sm text-muted-foreground">최근 {within}거래일 안에 드문 신호(구조·52주/연중 극값·중기 교차·추세전환 확인·MACD 0선·RSI 탈출·볼린저 복귀·ADX 통과)는 없습니다.{rest.length > 0 && ` 잦은 신호 ${formatNumber(rest.length)}개는 아래에 있습니다.`}</p>
          : <ul className="space-y-1.5">{notable.map(s => <li key={s.id} className="flex flex-wrap items-baseline gap-x-2 text-sm"><Badge className="font-normal">{s.label}</Badge><span className="tabular-nums text-caption text-muted-foreground">{s.date}</span>{s.value != null && s.reference != null && <span className="text-caption text-muted-foreground">{evidenceValue(s.value)} / 기준 {evidenceValue(s.reference)}</span>}</li>)}</ul>}
      </div>

      {grouped.length > 0 && <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="h-7 px-2 text-caption">잦은 신호 {formatNumber(rest.length)}개 보기<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 pt-2">{grouped.map(([category, items]) => <div key={category} className="space-y-1"><p className="text-caption font-medium text-muted-foreground">{GROUP_LABEL[category] ?? category}</p><ul className="space-y-1">{items.map(s => <li key={s.id} className="flex flex-wrap items-baseline gap-x-2 text-sm"><span>{s.label}</span><span className="tabular-nums text-caption text-muted-foreground">{s.date}</span></li>)}</ul></div>)}</CollapsibleContent></Collapsible>}
      </CollapsibleContent></Collapsible>
      <Collapsible open={commentaryOpen} onOpenChange={setCommentaryOpen}><CollapsibleTrigger asChild><Button variant="ghost" className="min-h-11 h-auto w-full justify-between whitespace-normal text-left"><span className="flex items-center gap-2"><Sparkles className="size-4" />AI 해설 보기</span><ChevronDown className="size-4 shrink-0" /></Button></CollapsibleTrigger><CollapsibleContent className="pt-2">{commentaryOpen && <Commentary code={code} market={market} within={within} enabled={!!scan} />}</CollapsibleContent></Collapsible>
      {scan.unavailable.length > 0 && <p className="text-caption text-muted-foreground">평가하지 못한 조건 {formatNumber(scan.unavailable.length)}개: {scan.unavailable.slice(0, 4).map(u => `${u.label}${u.reason ? ` (${EXCLUSION_LABELS[u.reason] ?? u.reason})` : ''}`).join(' · ')}{scan.unavailable.length > 4 ? ' 외' : ''}</p>}
      <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="text-caption">평가 범위·계산 기준<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-2 pt-2 text-caption text-muted-foreground"><p>검사 {formatNumber(scan.counts.evaluated)}개 · 충족 {formatNumber(scan.counts.passed)} · 불충족 {formatNumber(scan.counts.failed)} · 미평가 {formatNumber(scan.counts.unavailable)}</p><p>기본 매개변수의 정해진 규칙으로 계산합니다. 상승·하락 조건이 함께 있으므로 충족 개수는 투자 매력 점수가 아닙니다.</p></CollapsibleContent></Collapsible>
    </>}
  </section>
}
