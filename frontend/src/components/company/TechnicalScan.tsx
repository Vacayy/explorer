import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, X } from 'lucide-react'
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
import { formatNumber } from '@/utils/format'

/** 기업 페이지 차트의 '기술적 분석': 카탈로그 전략 51개를 이 종목 시세에 전부 돌린 결과. D-190. */
export interface ScanEntry { id: string; label: string; category: string; status: 'pass' | 'fail' | 'unavailable'; date: string | null; value: number | null; reference: number | null; reason: string | null; within_days: number }
export interface TechnicalScanResult {
  code: string; market: 'kr' | 'us'; as_of: string | null; within: number; sessions: number
  signals: ScanEntry[]; states: ScanEntry[]; unavailable: ScanEntry[]
  counts: { evaluated: number; passed: number; failed: number; unavailable: number }
  markers: { time: string; label: string; kind: 'signal' | 'pivot'; price?: number | null }[]
  lines: { id: string; label: string; points: { time: string; value: number }[] }[]
}

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
      {scan.unavailable.length > 0 && <p className="text-caption text-muted-foreground">평가하지 못한 조건 {formatNumber(scan.unavailable.length)}개: {scan.unavailable.slice(0, 4).map(u => u.label).join(' · ')}{scan.unavailable.length > 4 ? ' 외' : ''} (시세 이력 부족)</p>}
      <p className="text-caption text-muted-foreground">카탈로그 기본 매개변수로 계산한 결정적 판정입니다. 신호는 조건 성립 사실이고 수익성이나 추천을 뜻하지 않습니다.</p>
    </>}
  </section>
}
