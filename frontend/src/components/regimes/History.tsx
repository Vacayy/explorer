import { useMemo } from "react"
import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import RegimeChart from "@/components/charts/RegimeChart"
import type { RegimeBandSpec, RegimeSeries } from "@/components/charts/RegimeChart"
import { BlockError } from "@/components/home/blockState"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { OVERLAY_KEYS, useRegimeOverlay } from "@/hooks/useRegimes"
import type { OverlayKey } from "@/hooks/useRegimes"
import { cn } from "@/lib/utils"
import { formatBp, formatLevel, formatPercent, formatYield } from "@/utils/format"
import type { RegimesResponse } from "@/types"
import { tone } from "./BrkPanel"
import { InfoTip } from "./Section"

/*
 * 국면 이력(docs/specs/market-regimes.md) — 홈 › 매크로 아래쪽 묶음. 옛 /regimes 화면의 지도·겹쳐 보기·약세장 표.
 * URL 상태: regime_range(지도 기간) · regime_overlay(겹쳐 볼 계열).
 */

const MAP_RANGES = { "10y": "10년", "20y": "20년", "50y": "50년", all: "전체" } as const
export type MapRange = keyof typeof MAP_RANGES
const OVERLAY_LABEL: Record<OverlayKey, string> = { curve: "장단기 금리차 10Y−2Y", us10y: "미 10년 금리", us2y: "미 2년 금리", baa10y: "Baa − 10Y", aaa10y: "Aaa − 10Y" }

const yearsBefore = (d: string, n: number) => `${Number(d.slice(0, 4)) - n}${d.slice(4)}`
const startOf = (data: RegimesResponse, range: MapRange) => range === "all" || !data.as_of ? "" : yearsBefore(data.as_of, Number(range.slice(0, -1)))

/** 국면 음영 — 약세장(사후)·조정·NBER 침체(사후)·10개월선 추세 띠(실시간) */
function regimeBands(d: RegimesResponse, withTrend: boolean): RegimeBandSpec[] {
  return [
    ...d.recessions.map(r => ({ start: r.start, end: r.end, color: "--chart-gray", title: `NBER 침체 ${r.start} ~ ${r.end}` })),
    ...d.phases.filter(p => p.kind === "bear").map(p => ({ start: p.start, end: p.end, color: "--down", faint: p.provisional,
      title: `약세장 ${p.start} ~ ${p.end} ${formatPercent(p.change_pct)} · 확정 ${p.confirm_date ?? "-"}` })),
    ...d.corrections.filter(c => c.near_threshold).map(c => ({ start: c.start, end: c.end ?? d.as_of ?? c.trough, color: "--chart-warning", faint: true,
      title: `임계 근접 조정 ${c.start} ~ ${c.end ?? "진행 중"} ${formatPercent(c.drawdown_pct)}` })),
    ...(withTrend ? d.trend.filter(t => t.state === "down").map(t => ({ start: t.start, end: t.end, color: "--down", strip: true,
      title: `10개월선 아래 ${t.start} ~ ${t.end}` })) : []),
  ]
}

/** 지도·겹쳐 보기의 URL 상태 */
export function useHistoryParams() {
  const [params, setParams] = useSearchParams()
  const rangeRaw = params.get("regime_range")
  const range: MapRange = rangeRaw && rangeRaw in MAP_RANGES ? rangeRaw as MapRange : "all"
  const overlayRaw = params.get("regime_overlay") as OverlayKey | null
  const overlay: OverlayKey = overlayRaw && (OVERLAY_KEYS as readonly string[]).includes(overlayRaw) ? overlayRaw : "curve"
  const set = (key: string, value: string | null) =>
    setParams(prev => { const n = new URLSearchParams(prev); if (value) n.set(key, value); else n.delete(key); return n }, { replace: true, preventScrollReset: true })
  return { range, overlay, setRange: (v: string) => set("regime_range", v === "all" ? null : v), setOverlay: (v: string) => set("regime_overlay", v === "curve" ? null : v) }
}

export function MapCard({ data, range, onRange }: { data: RegimesResponse; range: MapRange; onRange: (v: string) => void }) {
  const start = startOf(data, range)
  const series = useMemo<RegimeSeries[]>(() => [{ key: "spx", label: "S&P500 (로그)", color: "--chart-1",
    data: data.series.filter(([t]) => t >= start).map(([time, value]) => ({ time, value })) }], [data, start])
  const bands = useMemo(() => regimeBands(data, true), [data])
  return <Card id="history-map" className="scroll-mt-24">
    <CardHeader className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <CardTitle>국면 지도 — 지난 백 년의 강세장과 약세장</CardTitle>
          <span className="text-caption text-muted-foreground">{data.phases.length}개 국면 · {data.first_date?.slice(0, 4)}년부터</span>
        </div>
        <ToggleGroup type="single" value={range} onValueChange={v => { if (v) onRange(v) }} variant="outline" size="sm" aria-label="기간">
          {(Object.keys(MAP_RANGES) as MapRange[]).map(k => <ToggleGroupItem key={k} value={k} className="px-3">{MAP_RANGES[k]}</ToggleGroupItem>)}
        </ToggleGroup>
      </div>
      <Layers data={data} />
    </CardHeader>
    <CardContent><RegimeChart series={series} bands={bands} height={380} logScale formatValue={v => formatLevel(v)} /></CardContent>
  </Card>
}

function Layers({ data }: { data: RegimesResponse }) {
  const p = data.params
  const item = (swatch: string, label: string, badge: string, note: string) => <Tip key={label} note={note}>
    <span className={cn("size-3 rounded-sm", swatch)} />{label}<Badge variant="outline" className={cn("px-1 py-0 text-[10px] font-normal", badge === "실시간" && "border-chart-profit/40 text-chart-profit-dark")}>{badge}</Badge>
  </Tip>
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-caption text-muted-foreground">
    {item("bg-[color-mix(in_srgb,var(--down)_20%,transparent)]", `약세장 −${p.bear * 100}%`, "사후",
      `Lunde–Timmermann ${p.bear * 100}/${p.bull * 100}: 직전 저점 이후 최고 종가 대비 −${p.bear * 100}%면 그 고점부터 약세, 직전 고점 이후 최저 종가 대비 +${p.bull * 100}%면 그 저점부터 강세. 경계는 나중에야 확정됩니다(${p.version}).`)}
    {item("bg-[color-mix(in_srgb,var(--chart-warning)_20%,transparent)]", `임계 근접 조정 −${p.near * 100}%~`, "사후", "강세장 안에서 약세 문턱에 거의 닿은 하락입니다.")}
    {item("bg-[color-mix(in_srgb,var(--chart-gray)_30%,transparent)]", "NBER 침체", "사후", "FRED USREC. NBER 발표는 평균 7.8개월(4~21개월) 늦습니다.")}
    {item("h-1.5 bg-[color-mix(in_srgb,var(--down)_70%,transparent)]", `${p.trend_months}개월선 아래(바닥 띠)`, "실시간", "월말 종가가 10개월 단순이평 아래(Faber 2007). 그 달 말에 알 수 있었던 신호입니다.")}
  </div>
}

function Tip({ note, children }: { note: string; children: ReactNode }) {
  return <span className="flex items-center gap-1.5">{children}<InfoTip label="범례 설명" className="-ml-1">{note}</InfoTip></span>
}

/** 겹쳐 보기 — 같은 음영 위에 금리·신용 계열. 국면을 판정하지 않는 재료다 */
export function OverlayCard({ data, range, overlay, onOverlay }: { data: RegimesResponse; range: MapRange; overlay: OverlayKey; onOverlay: (v: string) => void }) {
  const q = useRegimeOverlay(overlay)
  const item = q.data?.items.find(i => i.key === overlay)
  const start = startOf(data, range)
  const series = useMemo<RegimeSeries[]>(() => item ? [{ key: overlay, label: `${OVERLAY_LABEL[overlay]} (${item.unit})`, color: "--chart-4",
    data: item.points.filter(([t]) => t >= start).map(([time, value]) => ({ time, value })) }] : [], [item, overlay, start])
  const bands = useMemo(() => regimeBands(data, false), [data])
  const fmt = (v: number | null) => item?.unit === "%" ? formatYield(v) : `${formatBp(v)}bp`
  const chg = (v: number | null) => v == null ? "-" : item?.unit === "%" ? `${formatBp(v * 100, true)}bp` : `${formatBp(v, true)}bp`
  return <Card id="overlay" className="scroll-mt-24">
    <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
      <div className="flex items-center gap-1">
        <CardTitle>겹쳐 보기 — 같은 음영 위에서 금리·신용을 비교</CardTitle>
        <InfoTip label="겹쳐 보기 설명">국면을 판정하지 않는 재료입니다. 같은 약세장·침체 음영 위에서 직접 비교하세요.</InfoTip>
      </div>
      <ToggleGroup type="single" value={overlay} onValueChange={v => { if (v) onOverlay(v) }} variant="outline" size="sm" aria-label="겹쳐 볼 계열" className="flex-wrap">
        {OVERLAY_KEYS.map(k => <ToggleGroupItem key={k} value={k} className="px-2.5 text-caption">{OVERLAY_LABEL[k]}</ToggleGroupItem>)}
      </ToggleGroup>
    </CardHeader>
    <CardContent className="space-y-1.5">
      {q.isPending ? <Skeleton className="h-[240px] w-full" />
        : q.isError ? <BlockError message="계열을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
        : !item?.points.length ? <p className="py-10 text-sm text-muted-foreground">이 계열은 아직 관측이 없습니다. 다음 리스크 지표 갱신 때 채워집니다.</p>
        : <>
          <p className="text-sm">{OVERLAY_LABEL[overlay]} 지금 <b className="tabular-nums">{fmt(item.value)}</b> · 20일 변화 <span className={cn("tabular-nums", tone(item.change_20))}>{chg(item.change_20)}</span></p>
          <RegimeChart series={series} bands={bands} height={240} zeroLine={overlay === "curve"} />
          <p className="text-caption text-muted-foreground">{item.points[0][0]}부터 관측 · <a href={item.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{item.source}</a></p>
        </>}
    </CardContent>
  </Card>
}

export function BearTable({ data }: { data: RegimesResponse }) {
  const bears = data.phases.filter(p => p.kind === "bear").reverse()
  const near = data.corrections.filter(c => c.near_threshold).reverse()
  const half = Math.ceil(bears.length / 2)
  const table = (rows: typeof bears) => <Table>
    <TableHeader><TableRow>
      <TableHead>고점</TableHead><TableHead>저점</TableHead><TableHead className="text-right">하락</TableHead>
      <TableHead className="text-right">기간</TableHead><TableHead className="text-right">확정까지</TableHead>
    </TableRow></TableHeader>
    <TableBody>{rows.map(p => <TableRow key={p.start}>
      <TableCell className="font-mono tabular-nums">{p.start}</TableCell>
      <TableCell className="font-mono tabular-nums">{p.provisional ? "진행 중" : p.end}</TableCell>
      <TableCell className={cn("text-right font-mono tabular-nums", tone(p.change_pct))}>{formatPercent(p.change_pct)}</TableCell>
      <TableCell className="text-right tabular-nums">{p.days.toLocaleString("ko-KR")}일</TableCell>
      <TableCell className="text-right tabular-nums text-muted-foreground" title={p.confirm_date ?? undefined}>{p.confirm_lag_days != null ? `${p.confirm_lag_days}일` : "-"}</TableCell>
    </TableRow>)}</TableBody>
  </Table>
  return <Card id="bears" className="scroll-mt-24">
    <CardHeader className="flex flex-row items-center gap-1 space-y-0">
      <CardTitle>S&P500 약세장 {bears.length}번 ({data.first_date?.slice(0, 4)}~)</CardTitle>
      <InfoTip label="약세장 표 설명">종가 기준 규칙이라 공개 목록(Yardeni 등)과 대부분 같지만, 2000~02년과 2007~09년은 각각 둘로 나뉩니다 — 사이의 +21%·+24% 반등이 강세 문턱을 넘기 때문입니다. '확정까지'는 고점에서 규칙이 처음 충족된 날까지의 일수입니다.</InfoTip>
    </CardHeader>
    <CardContent className="space-y-4">
      <div className="grid gap-x-8 lg:grid-cols-2">{table(bears.slice(0, half))}{table(bears.slice(half))}</div>
      {near.length > 0 && <p className="text-caption text-muted-foreground">
        임계 근접 조정(−{data.params.near * 100}% 이상, 약세 아님): {near.map(c => `${c.start.slice(0, 7)} ${formatPercent(c.drawdown_pct)}`).join(" · ")}
      </p>}
    </CardContent>
  </Card>
}

/** 모바일 국면 이력 — 지도 최근 20년 + 최근 약세장 4건, 나머지는 전체 화면으로 (Mobile-Macro) */
export function HistoryCompact({ data }: { data: RegimesResponse }) {
  const start = startOf(data, "20y")
  const series = useMemo<RegimeSeries[]>(() => [{ key: "spx", label: "S&P500 (로그)", color: "--chart-1",
    data: data.series.filter(([t]) => t >= start).map(([time, value]) => ({ time, value })) }], [data, start])
  const bands = useMemo(() => regimeBands(data, true), [data])
  const bears = data.phases.filter(p => p.kind === "bear").reverse()
  return <Card id="history-map" className="scroll-mt-24">
    <CardHeader><CardTitle>국면 이력</CardTitle></CardHeader>
    <CardContent className="space-y-3">
      <RegimeChart series={series} bands={bands} height={240} logScale formatValue={v => formatLevel(v)} />
      <p className="text-caption text-muted-foreground">최근 20년 · 파랑 = 약세장 · 주황 = 임계 근접 조정 · 회색 = 침체 · 바닥 띠 = 10개월선 아래</p>
      <ul className="divide-y border-y text-sm">{bears.slice(0, 4).map(p => <li key={p.start} className="flex justify-between py-2 font-mono tabular-nums">
        <span>{p.start.slice(0, 7)} ~ {p.provisional ? "진행 중" : p.end.slice(0, 7)}</span><span className={tone(p.change_pct)}>{formatPercent(p.change_pct)}</span>
      </li>)}</ul>
      <Link to="/home/macro?macro_view=full#history" className="inline-block text-caption underline underline-offset-2">약세장 {bears.length}번 · 버크셔 vs 지수 ›</Link>
    </CardContent>
  </Card>
}
