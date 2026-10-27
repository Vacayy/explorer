import { useMemo } from "react"
import { useSearchParams } from "react-router-dom"
import { RefreshCw } from "lucide-react"
import { toast } from "sonner"
import RegimeChart from "@/components/charts/RegimeChart"
import type { RegimeBandSpec, RegimeSeries } from "@/components/charts/RegimeChart"
import { PageContainer } from "@/components/shared/PageContainer"
import { ErrorState } from "@/components/shared/ErrorState"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { OVERLAY_KEYS, useCollectRegimes, useRegimeOverlay, useRegimes } from "@/hooks/useRegimes"
import type { OverlayKey } from "@/hooks/useRegimes"
import { cn } from "@/lib/utils"
import { formatLevel, formatPercent } from "@/utils/format"
import type { RegimesResponse } from "@/types"
import { BrkPanel, tone } from "./BrkPanel"
import { NowPanel } from "./NowPanel"

const MAP_RANGES = { "10y": "10년", "20y": "20년", "50y": "50년", all: "전체" } as const
type MapRange = keyof typeof MAP_RANGES
const OVERLAY_LABEL: Record<OverlayKey, string> = { curve: "장단기 금리차 10Y−2Y", us10y: "미 10년 금리", us2y: "미 2년 금리", baa10y: "Baa − 10Y", aaa10y: "Aaa − 10Y" }

const yearsBefore = (d: string, n: number) => `${Number(d.slice(0, 4)) - n}${d.slice(4)}`

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

/**
 * 국면 이력(docs/specs/market-regimes.md) — 탐색 › 국면 이력. 홈 '국면·리스크'가 오늘의 포스처라면 여기는 과거 지도다.
 * URL 상태: regime_range(지도 기간) · regime_overlay(겹쳐 볼 계열) · brk_bench·brk_view·brk_range(버크셔 패널).
 */
export default function RegimesPage() {
  const [params, setParams] = useSearchParams()
  const q = useRegimes()
  const collect = useCollectRegimes()
  const rangeRaw = params.get("regime_range")
  const range: MapRange = rangeRaw && rangeRaw in MAP_RANGES ? rangeRaw as MapRange : "all"
  const overlayRaw = params.get("regime_overlay") as OverlayKey | null
  const overlay: OverlayKey = overlayRaw && (OVERLAY_KEYS as readonly string[]).includes(overlayRaw) ? overlayRaw : "curve"
  const set = (key: string, value: string | null) =>
    setParams(prev => { const n = new URLSearchParams(prev); if (value) n.set(key, value); else n.delete(key); return n }, { replace: true })
  const run = () => collect.mutate(undefined, {
    onSuccess: r => {
      const failed = r.results.filter(x => x.status === "error")
      if (failed.length) toast.error(`수집 실패: ${failed.map(f => `${f.key}(${f.error ?? ""})`).join(", ")}`)
      else toast.success(`수집 완료 · ${r.results.reduce((a, x) => a + x.rows, 0).toLocaleString("ko-KR")}행`)
    },
    onError: () => toast.error("수집 요청이 실패했습니다."),
  })
  const collectButton = <Button variant="outline" size="sm" onClick={run} disabled={collect.isPending}>
    {collect.isPending ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />}이력 수집
  </Button>

  if (q.isPending) return <PageContainer><Skeleton className="h-8 w-60" /><Skeleton className="h-[420px] w-full rounded-xl" /><Skeleton className="h-[560px] w-full rounded-xl" /></PageContainer>
  if (q.isError) return <PageContainer><ErrorState message="국면 이력을 불러오지 못했습니다." onRetry={() => void q.refetch()} /></PageContainer>
  const d = q.data
  if (!d.phases.length) return <PageContainer>
    <h2 className="text-xl font-bold">국면 이력</h2>
    <Card><CardContent className="space-y-3 py-12 text-center">
      <p className="font-medium">아직 지수 이력이 없습니다</p>
      <p className="text-sm text-muted-foreground">S&P500(1927~)·나스닥·버크셔 일별 시세와 NBER 침체 월을 처음 한 번 전부 받습니다(수십 초).</p>
      <div>{collectButton}</div>
    </CardContent></Card>
  </PageContainer>

  const cur = d.current
  return <PageContainer>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <h2 className="text-xl font-bold">국면 이력</h2>
        {cur && <p className="text-sm text-muted-foreground">
          지금 S&P500은 <span className={cn("font-medium", cur.kind === "bear" ? "text-down" : "text-foreground")}>{cur.kind === "bear" ? "약세장" : "강세장"}</span>(잠정, {cur.start}~)
          · 고점 대비 <span className={cn("tabular-nums", tone(cur.from_peak_pct))}>{formatPercent(cur.from_peak_pct)}</span>
          · 저점 대비 <span className={cn("tabular-nums", tone(cur.from_trough_pct))}>{formatPercent(cur.from_trough_pct)}</span>
          {cur.trend && <> · 10개월선 {cur.trend === "up" ? "위" : "아래"}</>}
        </p>}
      </div>
      <div className="flex items-center gap-2 text-caption text-muted-foreground">{d.as_of && <span>{d.as_of} 종가 기준</span>}{collectButton}</div>
    </div>

    <nav aria-label="이 페이지에서" className="flex flex-wrap gap-1.5 text-caption">
      {[["#now-state", "1 추세 이탈"], ["#now-meaning", "2 금리의 뜻"], ["#now-temp", "3 온도"], ["#now-premises", "4 구루 전제"], ["#history", "국면 이력"], ["#brk", "버크셔 vs 지수"]].map(([href, label]) =>
        <a key={href} href={href} className="rounded-full border px-2.5 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">{label}</a>)}
    </nav>
    <NowPanel regimes={d} />
    <div id="history" className="scroll-mt-24 space-y-1 pt-4">
      <h3 className="text-base font-semibold">국면 이력 — 지난 백 년의 강세장과 약세장</h3>
      <p className="text-caption text-muted-foreground">위의 '지금' 판정이 어떤 역사 위에 서 있는지 봅니다. 여기의 약세장 구간은 지나고 나서야 그을 수 있는 선(사후 판정)입니다.</p>
    </div>
    <MapCard data={d} range={range} onRange={v => set("regime_range", v === "all" ? null : v)} />
    <OverlayCard data={d} range={range} overlay={overlay} onOverlay={v => set("regime_overlay", v === "curve" ? null : v)} />
    <div id="brk" className="scroll-mt-24"><BrkPanel /></div>
    <BearTable data={d} />
  </PageContainer>
}

function MapCard({ data, range, onRange }: { data: RegimesResponse; range: MapRange; onRange: (v: string) => void }) {
  const start = range === "all" || !data.as_of ? "" : yearsBefore(data.as_of, Number(range.slice(0, -1)))
  const series = useMemo<RegimeSeries[]>(() => [{ key: "spx", label: "S&P500 (로그)", color: "--chart-1",
    data: data.series.filter(([t]) => t >= start).map(([time, value]) => ({ time, value })) }], [data, start])
  const bands = useMemo(() => regimeBands(data, true), [data])
  return <Card>
    <CardHeader className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>국면 지도</CardTitle>
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
  const item = (swatch: string, label: string, badge: string, note: string) => <span className="flex items-center gap-1.5" title={note}>
    <span className={cn("size-3 rounded-sm", swatch)} />{label}<Badge variant="outline" className="px-1 py-0 text-[10px] font-normal">{badge}</Badge>
  </span>
  return <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-caption text-muted-foreground">
    {item("bg-[color-mix(in_srgb,var(--down)_20%,transparent)]", `약세장 −${p.bear * 100}%`, "사후",
      `Lunde–Timmermann ${p.bear * 100}/${p.bull * 100}: 직전 저점 이후 최고 종가 대비 −${p.bear * 100}%면 그 고점부터 약세, 직전 고점 이후 최저 종가 대비 +${p.bull * 100}%면 그 저점부터 강세. 경계는 나중에야 확정된다(${p.version}).`)}
    {item("bg-[color-mix(in_srgb,var(--chart-warning)_20%,transparent)]", `임계 근접 조정 −${p.near * 100}%~`, "사후", "강세장 안에서 약세 문턱에 거의 닿은 하락")}
    {item("bg-[color-mix(in_srgb,var(--chart-gray)_30%,transparent)]", "NBER 침체", "사후", "FRED USREC. NBER 발표는 평균 7.8개월(4~21개월) 늦다")}
    {item("h-1.5 bg-[color-mix(in_srgb,var(--down)_70%,transparent)]", `${p.trend_months}개월선 아래(바닥 띠)`, "실시간", "월말 종가가 10개월 단순이평 아래(Faber 2007). 그 달 말에 알 수 있었던 신호")}
  </div>
}

function OverlayCard({ data, range, overlay, onOverlay }: { data: RegimesResponse; range: MapRange; overlay: OverlayKey; onOverlay: (v: string) => void }) {
  const q = useRegimeOverlay(overlay)
  const item = q.data?.items.find(i => i.key === overlay)
  const start = range === "all" || !data.as_of ? "" : yearsBefore(data.as_of, Number(range.slice(0, -1)))
  const series = useMemo<RegimeSeries[]>(() => item ? [{ key: overlay, label: `${OVERLAY_LABEL[overlay]} (${item.unit})`, color: "--chart-4",
    data: item.points.filter(([t]) => t >= start).map(([time, value]) => ({ time, value })) }] : [], [item, overlay, start])
  const bands = useMemo(() => regimeBands(data, false), [data])
  return <Card>
    <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
      <CardTitle>겹쳐 보기</CardTitle>
      <Select value={overlay} onValueChange={onOverlay}>
        <SelectTrigger className="h-8 w-48" aria-label="겹쳐 볼 계열"><SelectValue /></SelectTrigger>
        <SelectContent>{OVERLAY_KEYS.map(k => <SelectItem key={k} value={k}>{OVERLAY_LABEL[k]}</SelectItem>)}</SelectContent>
      </Select>
    </CardHeader>
    <CardContent className="space-y-1.5">
      {q.isPending ? <Skeleton className="h-[240px] w-full" />
        : q.isError ? <ErrorState message="계열을 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : !item?.points.length ? <p className="py-12 text-center text-sm text-muted-foreground">이 계열의 관측이 아직 없습니다. 홈 › 국면·리스크에서 Risk 지표를 갱신하세요.</p>
        : <>
          <RegimeChart series={series} bands={bands} height={240} zeroLine={overlay === "curve"} />
          <p className="text-caption text-muted-foreground">
            {item.points[0][0]}부터 관측 · <a href={item.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{item.source}</a>
            {" "}· 국면을 판정하지 않는 재료입니다. 같은 음영 위에서 직접 비교하세요.
          </p>
        </>}
    </CardContent>
  </Card>
}

function BearTable({ data }: { data: RegimesResponse }) {
  const bears = data.phases.filter(p => p.kind === "bear").reverse()
  const near = data.corrections.filter(c => c.near_threshold).reverse()
  return <Card>
    <CardHeader className="space-y-1.5">
      <CardTitle>S&P500 약세장 {bears.length}번 ({data.first_date?.slice(0, 4)}~)</CardTitle>
      <p className="text-caption leading-relaxed text-muted-foreground">
        종가 기준 규칙이라 공개 목록(Yardeni 등)과 대부분 같지만, 2000~02년과 2007~09년은 각각 둘로 나뉩니다 — 사이의 +21%·+24% 반등이 강세 문턱을 넘기 때문입니다.
        '확정까지'는 고점에서 규칙이 처음 충족된 날까지의 일수입니다.
      </p>
    </CardHeader>
    <CardContent className="space-y-4">
      <Table>
        <TableHeader><TableRow>
          <TableHead>고점</TableHead><TableHead>저점</TableHead><TableHead className="text-right">하락</TableHead>
          <TableHead className="text-right">기간</TableHead><TableHead className="text-right">확정까지</TableHead>
        </TableRow></TableHeader>
        <TableBody>{bears.map(p => <TableRow key={p.start}>
          <TableCell className="tabular-nums">{p.start}</TableCell>
          <TableCell className="tabular-nums">{p.provisional ? "진행 중" : p.end}</TableCell>
          <TableCell className={cn("text-right tabular-nums", tone(p.change_pct))}>{formatPercent(p.change_pct)}</TableCell>
          <TableCell className="text-right tabular-nums">{p.days.toLocaleString("ko-KR")}일</TableCell>
          <TableCell className="text-right tabular-nums text-muted-foreground" title={p.confirm_date ?? undefined}>{p.confirm_lag_days != null ? `${p.confirm_lag_days}일` : "-"}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
      {near.length > 0 && <p className="text-caption text-muted-foreground">
        임계 근접 조정(−{data.params.near * 100}% 이상, 약세 아님): {near.map(c => `${c.start.slice(0, 7)} ${formatPercent(c.drawdown_pct)}`).join(" · ")}
      </p>}
    </CardContent>
  </Card>
}
