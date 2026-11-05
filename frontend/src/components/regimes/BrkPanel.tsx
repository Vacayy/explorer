import { useMemo } from "react"
import { useSearchParams } from "react-router-dom"
import RegimeChart from "@/components/charts/RegimeChart"
import type { RegimeBandSpec, RegimeSeries } from "@/components/charts/RegimeChart"
import { ErrorState } from "@/components/shared/ErrorState"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useBrk } from "@/hooks/useRegimes"
import { cn } from "@/lib/utils"
import { formatPercent, formatPp } from "@/utils/format"
import { InfoTip } from "./Section"
import type { BrkBenchKey, BrkRange, BrkResponse } from "@/types"

export const BENCH_LABEL: Record<BrkBenchKey, string> = { sp500tr: "S&P500 총수익", sp500: "S&P500", nasdaq: "나스닥" }
export const RANGE_LABEL: Record<BrkRange, string> = { "1y": "1년", "3y": "3년", "5y": "5년", "10y": "10년", "20y": "20년", all: "전체" }
export type BrkView = "compare" | "spread"

/** URL이 단일 소스 — 위젯과 페이지가 brk_bench·brk_view를 공유한다 */
export function useBrkParams(defaultRange: BrkRange) {
  const [params, setParams] = useSearchParams()
  const benchRaw = params.get("brk_bench")
  const bench: BrkBenchKey = benchRaw === "sp500" || benchRaw === "nasdaq" ? benchRaw : "sp500tr"
  const view: BrkView = params.get("brk_view") === "spread" ? "spread" : "compare"
  const rangeRaw = params.get("brk_range") as BrkRange | null
  const range: BrkRange = rangeRaw && rangeRaw in RANGE_LABEL ? rangeRaw : defaultRange
  const set = (key: string, value: string | null) =>
    setParams(prev => { const n = new URLSearchParams(prev); if (value) n.set(key, value); else n.delete(key); return n }, { replace: true })
  return { bench, view, range, set }
}

export const tone = (v: number | null | undefined) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up-ink" : "text-down-ink"

/** 약세장·침체 음영 — 국면은 항상 S&P500 기준 */
export function brkBands(data: BrkResponse): RegimeBandSpec[] {
  return data.bands.map(b => b.kind === "bear"
    ? { start: b.start, end: b.end, color: "--down", faint: b.provisional, title: `약세장 ${b.start} ~ ${b.end}${b.provisional ? " (잠정)" : ""}` }
    : { start: b.start, end: b.end, color: "--chart-gray", title: `NBER 침체 ${b.start} ~ ${b.end}` })
}

/** 비교(누적%) 또는 스프레드(상대강도, 시작=100) 계열 */
export function brkSeries(data: BrkResponse, view: BrkView): RegimeSeries[] {
  return view === "spread"
    ? [{ key: "rs", label: `BRK ÷ ${data.bench.label} (시작=100)`, color: "--chart-1", data: data.points.map(p => ({ time: p.date, value: p.rs })) }]
    : [{ key: "brk", label: "BRK.B", color: "--chart-1", data: data.points.map(p => ({ time: p.date, value: p.brk_pct })) },
       { key: "bench", label: data.bench.label, color: "--chart-4", data: data.points.map(p => ({ time: p.date, value: p.bench_pct })) }]
}

export function BrkControls({ bench, view, range, set, ranges = true }: ReturnType<typeof useBrkParams> & { ranges?: boolean }) {
  return <div className="flex flex-wrap items-center gap-2">
    <ToggleGroup type="single" value={view} onValueChange={v => { if (v) set("brk_view", v === "spread" ? "spread" : null) }} variant="outline" size="sm" aria-label="보기">
      <ToggleGroupItem value="compare" className="px-3">비교</ToggleGroupItem>
      <ToggleGroupItem value="spread" className="px-3">스프레드</ToggleGroupItem>
    </ToggleGroup>
    <Select value={bench} onValueChange={v => set("brk_bench", v === "sp500tr" ? null : v)}>
      <SelectTrigger className="h-8 w-36" aria-label="비교 지수"><SelectValue /></SelectTrigger>
      <SelectContent>{(Object.keys(BENCH_LABEL) as BrkBenchKey[]).map(k => <SelectItem key={k} value={k}>{BENCH_LABEL[k]}</SelectItem>)}</SelectContent>
    </Select>
    {ranges && <Select value={range} onValueChange={v => set("brk_range", v === "all" ? null : v)}>
      <SelectTrigger className="h-8 w-24" aria-label="기간"><SelectValue /></SelectTrigger>
      <SelectContent>{(Object.keys(RANGE_LABEL) as BrkRange[]).map(k => <SelectItem key={k} value={k}>{RANGE_LABEL[k]}</SelectItem>)}</SelectContent>
    </Select>}
  </div>
}

/** 버크셔 vs 지수 — 비교/스프레드 · 롤링 12M 초과수익 · 국면별 표 (docs/specs/market-regimes.md §3) */
export function BrkPanel() {
  const p = useBrkParams("all")
  const q = useBrk(p.bench, p.range)
  const d = q.data
  const bands = useMemo(() => d ? brkBands(d) : [], [d])
  const main = useMemo(() => d ? brkSeries(d, p.view) : [], [d, p.view])
  const rolling = useMemo<RegimeSeries[]>(() => d ? [
    { key: "excess", label: "12개월 초과수익(%p)", color: "--chart-1", type: "histogram", posColor: "--up", negColor: "--down",
      data: d.rolling.map(r => ({ time: r.date, value: r.excess_12m })) },
    { key: "adj", label: "베타 조정(β·지수 차감)", color: "--foreground", lineWidth: 1,
      data: d.rolling.filter(r => r.beta_adj_12m != null).map(r => ({ time: r.date, value: r.beta_adj_12m! })) },
  ] : [], [d])
  const last = d?.rolling.at(-1)

  return <Card>
    <CardHeader className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <CardTitle>버크셔 vs 지수 — 국면마다 누가 이겼나</CardTitle>
          <InfoTip label="버크셔 비교 설명">국면 표와 요약은 기간 선택과 무관하게 전체 이력 기준입니다. 완결된 국면만 셉니다(잠정·데이터 시작 전에 시작한 국면 제외). BRK의 하락장 방어는 상당 부분 낮은 베타로 설명됩니다(Frazzini·Kabiller·Pedersen 2018, β≈0.7). 베타 조정은 국면 시작 시점의 직전 36개월 월간 베타로 BRK − β·지수를 계산합니다.</InfoTip>
        </div>
        {d?.as_of && <span className="text-caption text-muted-foreground">{d.start} ~ {d.as_of}</span>}
      </div>
      <BrkControls {...p} />
    </CardHeader>
    <CardContent className="space-y-5">
      {q.isPending ? <Skeleton className="h-[560px] w-full" />
        : q.isError ? <ErrorState message="버크셔 비교를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : !d || !d.points.length ? <p className="py-16 text-center text-sm text-muted-foreground">아직 버크셔 시세 이력이 없습니다. 첫 수집이 끝나면 채워집니다.</p>
        : <>
          <Notes data={d} />
          {last && <p className="text-sm">
            최근 12개월 BRK {formatPercent(last.brk_12m)} · {d.bench.label} {formatPercent(last.bench_12m)} →{" "}
            <span className={cn("font-medium tabular-nums", tone(last.excess_12m))}>초과 {formatPp(last.excess_12m, 1)}</span>
            {last.beta_36m != null && <span className="text-muted-foreground"> · β {last.beta_36m.toFixed(2)}(36개월 월간)</span>}
          </p>}
          <RegimeChart series={main} bands={bands} height={320} formatValue={v => p.view === "spread" ? v.toFixed(0) : `${v.toFixed(0)}%`} />
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">롤링 12개월 초과수익(월말) — 0 위면 BRK 우세</p>
            <RegimeChart series={rolling} bands={bands} height={200} zeroLine formatValue={v => `${v.toFixed(0)}%p`} />
          </div>
          <Legend />
          <PhaseTable data={d} />
        </>}
    </CardContent>
  </Card>
}

function Legend() {
  return <div className="flex flex-wrap gap-x-4 gap-y-1 text-caption text-muted-foreground">
    <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-[color-mix(in_srgb,var(--down)_20%,transparent)]" />약세장(S&P500 −20%, 사후)</span>
    <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-[color-mix(in_srgb,var(--chart-gray)_25%,transparent)]" />NBER 침체(사후, 발표 4~21개월 지연)</span>
  </div>
}

function Notes({ data }: { data: BrkResponse }) {
  const late = data.bench.first_date && data.brk_first_date && data.bench.first_date > data.brk_first_date
  return <div className="flex flex-wrap gap-1.5">
    {!data.bench.dividends && <Badge variant="outline" className="font-normal">배당 제외 지수 — BRK가 배당수익률만큼 유리하게 보입니다</Badge>}
    {late && <Badge variant="outline" className="font-normal">{data.bench.label} 이력이 {data.bench.first_date}부터라 그 이전은 비교하지 않습니다</Badge>}
    {data.start && data.start < "1996-05-09" && <Badge variant="outline" className="font-normal">1996-05 이전은 BRK.A를 BRK.B 단위로 환산</Badge>}
  </div>
}

function PhaseTable({ data }: { data: BrkResponse }) {
  const rows = [...data.phases].reverse()
  const s = data.summary
  return <div className="space-y-3">
    <div className="grid gap-2 sm:grid-cols-2">
      {(["bear", "bull"] as const).map(k => s[k] && <div key={k} className="rounded-xl bg-muted/50 px-4 py-3 text-sm">
        <p className="font-medium">{k === "bear" ? "약세장" : "강세장"} {s[k]!.n}번 중 BRK 우세 {s[k]!.brk_wins}번</p>
        <p className="text-caption text-muted-foreground">초과수익 중앙값 <span className={cn("tabular-nums", tone(s[k]!.median_excess_pct))}>{formatPp(s[k]!.median_excess_pct, 1)}</span>
          {" "}· 베타 조정 후 우세 {s[k]!.beta_adj_wins}/{s[k]!.beta_adj_n}번</p>
      </div>)}
    </div>
    <Table>
      <TableHeader><TableRow>
        <TableHead>국면</TableHead><TableHead>기간</TableHead><TableHead className="text-right">S&P500</TableHead>
        <TableHead className="text-right">BRK</TableHead><TableHead className="text-right">{data.bench.label}</TableHead>
        <TableHead className="text-right">초과</TableHead><TableHead className="text-right">베타 조정</TableHead><TableHead className="text-right">확정까지</TableHead>
      </TableRow></TableHeader>
      <TableBody>{rows.map(r => <TableRow key={r.start}>
        <TableCell><Badge variant={r.kind === "bear" ? "secondary" : "outline"} className="font-normal">{r.kind === "bear" ? "약세" : "강세"}{r.provisional ? " · 잠정" : ""}</Badge></TableCell>
        <TableCell className="whitespace-nowrap tabular-nums text-caption">{r.clipped_start ?? r.start} ~ {r.provisional ? "진행 중" : r.end}{r.clipped_start && <span className="text-muted-foreground"> (국면 시작 {r.start})</span>}</TableCell>
        <TableCell className={cn("text-right tabular-nums", tone(r.spx_change_pct))}>{formatPercent(r.spx_change_pct)}</TableCell>
        <TableCell className={cn("text-right tabular-nums", tone(r.brk_pct))}>{formatPercent(r.brk_pct)}</TableCell>
        <TableCell className={cn("text-right tabular-nums", tone(r.bench_pct))}>{formatPercent(r.bench_pct)}</TableCell>
        <TableCell className={cn("text-right font-medium tabular-nums", tone(r.excess_pct))}>{formatPp(r.excess_pct, 1)}</TableCell>
        <TableCell className={cn("text-right tabular-nums", tone(r.beta_adj_pct))} title={r.beta != null ? `β ${r.beta.toFixed(2)}` : "베타 계산에 36개월 이력 필요"}>{formatPp(r.beta_adj_pct, 1)}</TableCell>
        <TableCell className="text-right tabular-nums text-caption text-muted-foreground" title={r.confirm_date ? `확정일 ${r.confirm_date}` : undefined}>{r.confirm_lag_days != null ? `${r.confirm_lag_days}일` : "-"}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
  </div>
}
