import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, RefreshCw, Sparkles, X } from 'lucide-react'
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

/** 기업 페이지 차트의 '기술적 분석': 카탈로그 전략 51개를 이 종목 시세에 전부 돌린 결과. D-190. */
export interface ScanEntry { id: string; label: string; category: string; status: 'pass' | 'fail' | 'unavailable'; date: string | null; value: number | null; reference: number | null; reason: string | null; within_days: number }
export interface TechnicalScanResult {
  code: string; market: 'kr' | 'us'; as_of: string | null; within: number; sessions: number
  signals: ScanEntry[]; states: ScanEntry[]; unavailable: ScanEntry[]
  counts: { evaluated: number; passed: number; failed: number; unavailable: number }
  markers: { time: string; label: string; kind: 'signal' | 'pivot'; price?: number | null }[]
  lines: { id: string; label: string; points: { time: string; value: number }[] }[]
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
const NOTABLE = new Set(['high_52w', 'low_52w', 'high_ytd', 'low_ytd', 'golden_cross_20_60', 'dead_cross_20_60', 'trend_reversal_confirmed', 'macd_zero_cross', 'breakout_pullback_10d', 'volume_profile_up_60d', 'volume_profile_down_60d'])
const UP = /(상향|신고가|골든|매수|상승|지지|재돌파)/
const DOWN = /(하향|신저가|데드|이탈|하락)/
const GROUP_LABEL: Record<string, string> = { '가격 구조': '구조 (스윙·추세선·채널)', 시세동향: '가격·거래량', 지표신호: '이동평균·지표' }

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

export function TechnicalScan({ code, market, within, onWithin, onChart, onToggleChart, onClose }: {
  code: string; market: 'kr' | 'us'; within: number; onWithin: (value: number) => void; onChart: boolean; onToggleChart: (value: boolean) => void; onClose: () => void
}) {
  const query = useTechnicalScan(code, market, within, true)
  const scan = query.data
  const notable = useMemo(() => (scan?.signals ?? []).filter(isNotable), [scan])
  const rest = useMemo(() => (scan?.signals ?? []).filter(s => !isNotable(s)), [scan])
  const grouped = useMemo(() => { const map = new Map<string, ScanEntry[]>(); for (const s of rest) map.set(s.category, [...(map.get(s.category) ?? []), s]); return [...map.entries()] }, [rest])
  const activeStates = scan?.states.filter(s => s.status === 'pass') ?? []
  return <section aria-label="기술적 분석" className="space-y-4 rounded-xl border p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">기술적 분석</h3>
        {scan && <span className="text-caption text-muted-foreground">{scan.as_of} 기준 · {formatNumber(scan.sessions)}거래일 시세 · 조건 {formatNumber(scan.counts.evaluated)}개 중 통과 {formatNumber(scan.counts.passed)}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5"><Label htmlFor="scan-within" className="text-caption text-muted-foreground">신호 범위</Label>
          <Select value={String(within)} onValueChange={value => onWithin(Number(value))}><SelectTrigger id="scan-within" size="sm" className="h-7 w-auto min-w-28" aria-label="신호 범위"><SelectValue /></SelectTrigger><SelectContent>{[1, 3, 5, 10, 20].map(n => <SelectItem key={n} value={String(n)}>{n === 1 ? '기준일 당일' : `최근 ${n}거래일`}</SelectItem>)}</SelectContent></Select></div>
        <label className="flex items-center gap-1.5 text-caption text-muted-foreground"><Switch checked={onChart} onCheckedChange={onToggleChart} aria-label="차트에 표시" />차트에 표시</label>
        <Button variant="ghost" size="icon-sm" aria-label="기술적 분석 닫기" onClick={onClose}><X className="size-4" /></Button>
      </div>
    </div>
    {query.isPending && <div className="space-y-2" role="status" aria-label="분석 중"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /><Skeleton className="h-4 w-3/5" /></div>}
    {query.isError && <ErrorState message="기술적 분석을 계산하지 못했습니다." onRetry={() => query.refetch()} />}
    {scan && <>
      <div className="space-y-2">
        <h4 className="text-caption font-medium text-muted-foreground">특이점</h4>
        {notable.length === 0 ? <p className="text-sm text-muted-foreground">최근 {within}거래일 안에 드문 신호(구조·52주/연중 극값·중기 교차·추세전환 확인·MACD 0선)는 없습니다.{rest.length > 0 && ` 잦은 신호 ${formatNumber(rest.length)}개는 아래에 있습니다.`}</p>
          : <ul className="space-y-1.5">{notable.map(s => <li key={s.id} className="flex flex-wrap items-baseline gap-x-2 text-sm"><Badge className="font-normal">{s.label}</Badge><span className="tabular-nums text-caption text-muted-foreground">{s.date}</span>{s.value != null && s.reference != null && <span className="text-caption text-muted-foreground">{formatNumber(Math.round(s.value))} / 기준 {formatNumber(Math.round(s.reference))}</span>}</li>)}</ul>}
      </div>
      <div className="space-y-1">
        <h4 className="text-caption font-medium text-muted-foreground">현재 상태 · {scan.as_of}</h4>
        {activeStates.length === 0 ? <p className="text-sm text-muted-foreground">정배열·역배열, 저점 높이기·고점 낮추기, 신고가 근접 중 성립한 것이 없습니다.</p>
          : <div className="flex flex-wrap gap-1.5">{activeStates.map(s => <Badge key={s.id} variant="secondary" className="font-normal">{s.label}</Badge>)}</div>}
      </div>
      {grouped.length > 0 && <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="h-7 px-2 text-caption">잦은 신호 {formatNumber(rest.length)}개 보기<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 pt-2">{grouped.map(([category, items]) => <div key={category} className="space-y-1"><p className="text-caption font-medium text-muted-foreground">{GROUP_LABEL[category] ?? category}</p><ul className="space-y-1">{items.map(s => <li key={s.id} className="flex flex-wrap items-baseline gap-x-2 text-sm"><span>{s.label}</span><span className="tabular-nums text-caption text-muted-foreground">{s.date}</span></li>)}</ul></div>)}</CollapsibleContent></Collapsible>}
      <Commentary code={code} market={market} within={within} enabled={!!scan} />
      {scan.unavailable.length > 0 && <p className="text-caption text-muted-foreground">평가하지 못한 조건 {formatNumber(scan.unavailable.length)}개: {scan.unavailable.slice(0, 4).map(u => u.label).join(' · ')}{scan.unavailable.length > 4 ? ' 외' : ''} (시세 이력 부족)</p>}
      <p className="text-caption text-muted-foreground">카탈로그 기본 매개변수로 계산한 결정적 판정입니다. 신호는 조건 성립 사실이고 수익성이나 추천을 뜻하지 않습니다.</p>
    </>}
  </section>
}
