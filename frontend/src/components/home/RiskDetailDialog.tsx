import { Link } from "react-router-dom"
import AreaSeriesChart from "@/components/charts/AreaSeriesChart"
import MultiLineChart from "@/components/charts/MultiLineChart"
import { useChartTheme } from "@/components/charts/chartTheme"
import { BlockError, tone } from "@/components/home/blockState"
import { Seg } from "@/components/home/MarketFrame"
import { riskChange, riskValue } from "@/components/widgets/market"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useMarketRegime } from "@/hooks/useMarketRegime"
import { useRiskTiles } from "@/hooks/useRisk"
import { useUrlParam } from "@/hooks/useUrlParam"
import { fearGreedZone, lastMonths, longRangePosition } from "@/lib/macroPage"
import { cn } from "@/lib/utils"
import { formatLevel } from "@/utils/format"
import type { MarketSeries } from "@/types"

/** 홈 › 대시보드 국면·리스크에서 여는 상세 — URL `risk_detail`(지표 키 또는 regime)·`risk_range`가 상태 */
export const RISK_DETAIL_LABEL: Record<string, string> = { vix: "VIX", fear_greed: "공포·탐욕", hy: "HY OAS", curve: "10Y − 2Y" }
const RANGES = [{ key: "3m", label: "3개월", months: 3 }, { key: "1y", label: "1년", months: 12 }, { key: "5y", label: "5년", months: 60 }]

export function useRiskDetail() {
  const [open, setOpen] = useUrlParam("risk_detail", "")
  return { open, show: (key: string) => setOpen(key), close: () => setOpen("") }
}

export function RiskDetailDialog() {
  const { open, close } = useRiskDetail()
  const title = open === "regime" ? "국면 판정" : RISK_DETAIL_LABEL[open]
  return <Dialog open={!!title} onOpenChange={v => !v && close()}>
    <DialogContent className="max-h-[88dvh] overflow-y-auto sm:max-w-3xl">
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription className="sr-only">{open === "regime" ? "국장·미장 포스처와 판정 근거" : `${title} 추이와 장기 위치`}</DialogDescription>
      </DialogHeader>
      {open === "regime" ? <RegimeDetail /> : title ? <MetricDetail metric={open} /> : null}
      <Link to={open === "regime" ? "/home/macro" : "/home/macro#risk"} onClick={close} className="justify-self-end text-xs text-ink-3 hover:text-ink hover:underline">매크로에서 더 보기 ›</Link>
    </DialogContent>
  </Dialog>
}

function MetricDetail({ metric }: { metric: string }) {
  const q = useRiskTiles()
  const [range, setRange] = useUrlParam("risk_range", "1y")
  if (q.isPending) return <Skeleton className="h-[340px] w-full" />
  if (q.isError) return <BlockError message="지표를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
  const item = q.data.items.find(i => i.key === metric)
  if (!item || item.value == null) return <p className="text-sm text-muted-foreground">이 지표의 관측이 아직 없어요.</p>
  const months = RANGES.find(r => r.key === range)?.months ?? 12
  const pts = lastMonths(item.points, item.as_of, months)
  const vals = pts.map(p => p[1])
  const hi = vals.length ? pts[vals.indexOf(Math.max(...vals))] : null
  const lo = vals.length ? pts[vals.indexOf(Math.min(...vals))] : null
  const pos = metric === "fear_greed" ? null : longRangePosition(item.points, item.value, item.as_of)
  const zone = metric === "fear_greed" ? fearGreedZone(item.value) : null
  const fmt = (v: number) => riskValue(item.unit, v)
  return <div className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
      <Stat label={item.as_of ? `값 · ${item.as_of}` : "값"} value={fmt(item.value)} strong />
      <Stat label="20일 변화" value={<span className={tone(item.change_20)}>{riskChange(item.unit, item.change_20)}</span>} />
      {zone && <Stat label="구간" value={zone} />}
      {pos && <Stat label={`최근 ${pos.years}년 위치`} value={<Badge variant={pos.position === "높음" ? "up" : pos.position === "낮음" ? "down" : "neutral"}>{pos.position}</Badge>} />}
      {hi && <Stat label="기간 최고" value={`${fmt(hi[1])} · ${hi[0].slice(2).replaceAll("-", "/")}`} />}
      {lo && <Stat label="기간 최저" value={`${fmt(lo[1])} · ${lo[0].slice(2).replaceAll("-", "/")}`} />}
      <Seg label="기간" value={range} items={RANGES} onChange={setRange} className="ml-auto" />
    </div>
    {item.quality !== "fresh" && <p className="text-[11px] text-warn">{item.quality === "stale" ? `${item.lag_days ?? "?"}일 지연` : "갱신 실패"}</p>}
    {pts.length > 1
      ? <AreaSeriesChart data={pts.map(([time, value]) => ({ time, value }))} height={300} formatValue={fmt} />
      : <p className="text-sm text-muted-foreground">이 기간의 관측이 부족해요.</p>}
  </div>
}

function Stat({ label, value, strong }: { label: string; value: React.ReactNode; strong?: boolean }) {
  return <div className="flex flex-col gap-0.5">
    <span className="text-[11.5px] text-ink-3">{label}</span>
    <span className={cn("font-mono tabular-nums", strong ? "text-[22px]" : "text-sm")}>{value}</span>
  </div>
}

/** 판정 코드(pipeline/market_regime) → 화면 말 */
const KO: Record<string, string> = {
  extreme_fear: "극단적 공포", fear: "공포", neutral: "중립", greed: "탐욕", extreme_greed: "극단적 탐욕",
  oversold: "과매도", overbought: "과매수", calm: "안정", elevated: "높음", stress: "스트레스",
  up: "상승", flat: "횡보", down: "하락", unknown: "판단 불가",
}
const ko = (code: string) => KO[code] ?? code

const POSTURE_VARIANT: Record<string, "neutral" | "down" | "warn" | "up"> = { neutral: "neutral", caution: "down", risk: "warn", favorable: "up" }

function RegimeDetail() {
  const q = useMarketRegime()
  if (q.isPending) return <Skeleton className="h-[420px] w-full" />
  if (q.isError) return <BlockError message="국면 판정을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
  const d = q.data
  return <div className="flex min-w-0 flex-col gap-4">
    <p className="text-sm">{d.headline}</p>
    {d.kr && <Posture market="국장" posture={d.kr.posture} color={d.kr.posture_color} reason={d.kr.reason}
      rows={[[`오실레이터(${d.kr.oscillator.metric})`, `${d.kr.oscillator.value == null ? "-" : formatLevel(d.kr.oscillator.value)} · ${ko(d.kr.oscillator.zone)}`],
        ["추세(20 EMA)", `${d.kr.trend.ema == null ? "-" : formatLevel(d.kr.trend.ema)} · ${ko(d.kr.trend.dir)}`],
        ...(d.kr.volatility ? [[`변동성(${d.kr.volatility.metric})`, `${d.kr.volatility.value == null ? "-" : formatLevel(d.kr.volatility.value)} · ${ko(d.kr.volatility.band)}`] as [string, string]] : [])]}
      osc={d.kr.series.osc} ema={d.kr.series.osc_ema} oscLabel={d.kr.oscillator.metric} />}
    {d.us && <Posture market="미장" posture={d.us.posture} color={d.us.posture_color} reason={d.us.reason}
      rows={[["공포·탐욕", d.us.fear_greed ? `${formatLevel(d.us.fear_greed.score)} · ${ko(d.us.fear_greed.zone)}` : "-"],
        ["추세(20 EMA)", `${d.us.trend.ema == null ? "-" : formatLevel(d.us.trend.ema)} · ${ko(d.us.trend.dir)}`],
        ["VIX", d.us.vix ? `${formatLevel(d.us.vix.value)} · ${ko(d.us.vix.band)}` : "-"]]}
      osc={d.us.series.osc} ema={d.us.series.osc_ema} oscLabel="공포·탐욕" />}
    {d.degraded.length > 0 && <p className="text-[11px] text-warn">빠진 재료: {d.degraded.join(", ")}</p>}
  </div>
}

function Posture({ market, posture, color, reason, rows, osc, ema, oscLabel }: {
  market: string; posture: string; color: string; reason: string; rows: [string, string][]
  osc: MarketSeries; ema: MarketSeries; oscLabel: string
}) {
  const theme = useChartTheme()
  const emaBy = new Map(ema)
  const data = osc.map(([time, v]) => ({ time, osc: v, ema: emaBy.get(time) ?? null }))
  return <section className="flex min-w-0 flex-col gap-2 border-t pt-3" aria-label={`${market} 포스처`}>
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant={POSTURE_VARIANT[color] ?? "neutral"}>{market} {posture}</Badge>
      <span className="text-[13px] text-ink-2">{reason}</span>
    </div>
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-[13px] sm:grid-cols-3">
      {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-2 sm:flex-col sm:justify-start"><dt className="text-ink-3">{k}</dt><dd className="font-mono tabular-nums">{v}</dd></div>)}
    </dl>
    {data.length > 1 && <MultiLineChart data={data} height={180} showLegend
      lines={[{ key: "osc", label: oscLabel, color: theme.ink }, { key: "ema", label: "20 EMA", color: theme.ink3, lineStyle: 2 }]} />}
  </section>
}

