import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { MetricTrend } from "@/components/shared/MetricTrend"
import { SparkLine } from "@/components/shared/Spark"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { fmtValue } from "@/components/home/MacroLiquidity"
import { RiskCard, useRiskView, type RiskCardKind } from "@/components/home/RiskMonitoring"
import { Card } from "@/components/ui/card"
import { useIndices, useRiskWindow } from "@/hooks/useDashboard"
import { useKrMovers } from "@/hooks/useKrMovers"
import { useMacro } from "@/hooks/useMacro"
import { useMarketRegime } from "@/hooks/useMarketRegime"
import { useRetailSummary } from "@/hooks/useRetail"
import { useUsBriefing } from "@/hooks/useUsBriefing"
import { cn } from "@/lib/utils"
import { formatBp, formatLevel, formatPercent, formatRatio, formatYield } from "@/utils/format"
import type { WidgetBodyProps, WidgetMeta } from "./types"

/**
 * 시장 위젯 10종 — 요약층만 (docs/specs/home-widgets.md §3). 모두 캐시된 GET 훅만 읽고 갱신 버튼은 전체 보기 탭에 둔다.
 * 각 위젯은 { meta(기준 시각·고장), body }를 돌려주는 훅 + 본문 컴포넌트 한 쌍이다.
 */

const tone = (v: number | null | undefined) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up" : "text-down"
const stripCell = "flex min-w-0 flex-1 flex-col justify-center border-l px-3 first:border-l-0"

/* ── 지수 띠 ── */
export function useIndicesMeta(): WidgetMeta {
  const q = useIndices()
  return { asOf: q.data?.as_of ?? null, stale: !!q.data?.degraded.length }
}
export function IndicesBody(_: WidgetBodyProps) {
  const q = useIndices()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  return <div className="flex h-full items-stretch overflow-hidden">
    {q.data.items.map(r => (
      <div key={r.key} className={stripCell}>
        <span className="flex items-baseline justify-between gap-1 text-[11px]">
          <span className="truncate text-muted-foreground"><span className={cn("mr-1 inline-block size-1.5 rounded-full align-middle", r.is_open ? "bg-chart-green" : "bg-muted-foreground/40")} />{r.label}</span>
          <span className={cn("shrink-0 tabular-nums", tone(r.change_pct))}>{formatPercent(r.change_pct)}</span>
        </span>
        <span className="truncate text-sm font-semibold tabular-nums">{formatLevel(r.price)}</span>
        {/* 1Y 추이 — 남는 높이를 채운다(위젯을 키우면 같이 커진다) */}
        <div className="mt-1 min-h-3 flex-1"><SparkLine data={r.spark} height={20} className="h-full w-full" /></div>
      </div>
    ))}
  </div>
}

/* ── 시장 요약 띠 ── */
const CONTEXT_KEYS = ["usdkrw", "jpykrw", "us2y", "us10y", "oil", "gold", "btc"]
export function useContextMeta(): WidgetMeta {
  const q = useMacro()
  return { asOf: q.data?.as_of ?? null, stale: !!q.data?.degraded.length }
}
export function ContextBody(_: WidgetBodyProps) {
  const q = useMacro()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const items = CONTEXT_KEYS.map(k => q.data!.items.find(i => i.key === k)).filter(Boolean) as NonNullable<typeof q.data>["items"]
  return <div className="flex h-full items-stretch overflow-hidden">
    {items.map(m => (
      // 올리면(클릭·키보드도) 추이 차트 — 시장 브리핑 지표 띠와 같은 MetricTrend
      <MetricTrend key={m.key} label={m.label} points={m.dated_series} format={v => fmtValue({ ...m, value: v })}
        className={cn(stripCell, "h-full items-start gap-0 rounded-none py-0 text-left font-normal")}>
        <span className="truncate text-[11px] text-muted-foreground">{m.label}</span>
        <span className="truncate text-sm font-semibold tabular-nums">{fmtValue(m)}</span>
        <span className={cn("text-[11px] tabular-nums", tone(m.change_pct))}>{formatPercent(m.change_pct)}</span>
      </MetricTrend>
    ))}
  </div>
}

/* ── 어젯밤 미국장 ── */
export function useUsMeta(): WidgetMeta {
  const q = useUsBriefing(null)
  const d = q.data
  return { asOf: d?.trade_date ?? null, stale: !!d && (d.status !== "ok" || (d.stale_days ?? 0) > 1) }
}
export function UsBody({ h }: WidgetBodyProps) {
  const q = useUsBriefing(null)
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const top = d.clusters[0]
  const first = (d.synthesis?.drivers || d.synthesis?.issues || "").replace(/\[\d+\]/g, "").split(/(?<=[.다])\s/)[0]
  if (!top && !first) return <WidgetState empty emptyText="오늘 브리핑이 아직 없어요. 매일 06:30에 만들어집니다." />
  return <div className="flex h-full flex-col gap-2">
    {top && <WidgetHero value={`${top.label} ${formatRatio(top.share_pct)}`}
      aside={<span className={cn("text-sm tabular-nums", tone(top.median_change))}>중앙 {formatPercent(top.median_change)}</span>} />}
    {first && <p className={cn("text-[13px] leading-5 text-muted-foreground", h <= 3 ? "line-clamp-2" : "line-clamp-3")}>{first}</p>}
    {h > 3 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {d.idiosyncratic.slice(0, 3).map(m => (
        <li key={m.ticker} className="flex items-center justify-between gap-2 py-1.5">
          <span className="truncate"><span className="font-medium">{m.ticker}</span> <span className="text-muted-foreground">{m.name}</span></span>
          <span className={cn("shrink-0 tabular-nums", tone(m.change_pct))}>{formatPercent(m.change_pct)}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 전일 국장 거래대금 ── */
export function useKrMeta(): WidgetMeta {
  const q = useKrMovers()
  return { asOf: q.data?.trade_date ?? null, stale: !!q.data && q.data.status !== "ok" }
}
export function KrBody({ h }: WidgetBodyProps) {
  const q = useKrMovers()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.items.length) return <WidgetState empty emptyText="전일 거래대금 스냅샷이 없어요. 평일 16:20에 받습니다." />
  const top = d.clusters[0]
  const rows = d.items.slice(0, h > 3 ? 5 : 3)
  const max = Math.max(...rows.map(r => Math.abs(r.change_pct ?? 0)), 1)
  return <div className="flex h-full flex-col gap-2">
    {top && <WidgetHero value={`${top.label} ${formatRatio(top.share_pct)}`}
      aside={<span className={cn("text-sm tabular-nums", tone(top.median_change))}>중앙 {formatPercent(top.median_change)}</span>} />}
    <ul className="min-h-0 space-y-1 overflow-hidden text-[13px]">
      {rows.map(r => (
        <li key={r.stock_code} className="grid grid-cols-[minmax(0,1fr)_96px_56px] items-center gap-2">
          <Link to={`/analyze/${r.stock_code}/summary`} className="truncate hover:underline">{r.name}</Link>
          <span className="h-1.5 overflow-hidden rounded-full bg-muted"><span className={cn("block h-full rounded-full", (r.change_pct ?? 0) >= 0 ? "bg-up" : "bg-down")} style={{ width: `${Math.abs(r.change_pct ?? 0) / max * 100}%` }} /></span>
          <span className={cn("text-right tabular-nums", tone(r.change_pct))}>{formatPercent(r.change_pct)}</span>
        </li>
      ))}
    </ul>
  </div>
}

/* ── 시장 국면 ── */
export function useRegimeMeta(): WidgetMeta {
  const q = useMarketRegime()
  return { asOf: q.data?.as_of ?? null, stale: !!q.data?.degraded.length }
}
const POSTURE_TONE: Record<string, string> = { caution: "border-chart-warning/50 text-chart-warning", risk: "border-down/50 text-down", favorable: "border-up/50 text-up", neutral: "text-muted-foreground" }
export function RegimeBody({ h }: WidgetBodyProps) {
  const q = useMarketRegime()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.kr && !d.us) return <WidgetState empty emptyText="국면 판정 재료가 아직 없어요." />
  return <div className="flex h-full flex-col gap-2">
    <div className="flex flex-wrap gap-1.5">
      {d.kr && <Badge variant="outline" className={cn("text-xs", POSTURE_TONE[d.kr.posture_color])}>국장 {d.kr.posture}</Badge>}
      {d.us && <Badge variant="outline" className={cn("text-xs", POSTURE_TONE[d.us.posture_color])}>미장 {d.us.posture}</Badge>}
    </div>
    <p className={cn("text-[13px] leading-5 text-muted-foreground", h <= 2 ? "line-clamp-1" : "line-clamp-2")}>{d.headline}</p>
    {h > 2 && <div className="grid grid-cols-2 gap-2">
      <Tile label="공포탐욕" value={d.us?.fear_greed ? formatLevel(d.us.fear_greed.score) : "-"} sub={d.us?.fear_greed?.zone} />
      <Tile label="VIX" value={d.us?.vix ? formatLevel(d.us.vix.value) : "-"} sub={d.us?.vix?.band} />
    </div>}
    {d.degraded.length > 0 && <p className="text-[11px] text-chart-warning">빠진 재료: {d.degraded.join(", ")}</p>}
  </div>
}
function Tile({ label, value, sub }: { label: string; value: string; sub?: string | null }) {
  return <div className="rounded-lg bg-muted/60 px-2.5 py-1.5"><div className="text-[11px] text-muted-foreground">{label}</div>
    <div className="text-base font-semibold tabular-nums">{value}</div>{sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}</div>
}

/* ── Risk 단일 지표 ── */
function riskValue(unit: string, v: number | null) {
  return unit === "%" ? formatYield(v) : unit === "bp" ? (v == null ? "-" : `${formatBp(v)}bp`) : formatLevel(v)
}
function riskChange(unit: string, v: number | null) {
  if (v == null) return "-"
  return unit === "bp" ? `${formatBp(v, true)}bp` : unit === "%" ? `${formatBp(v * 100, true)}bp` : `${v > 0 ? "+" : ""}${formatLevel(v)}`
}
export function useRiskMeta(key: string): WidgetMeta {
  const q = useRiskWindow()
  const item = q.data?.items.find(i => i.key === key)
  return { asOf: item?.as_of ?? null, stale: !!item && item.quality !== "fresh" }
}
export function RiskBody({ metric, h }: WidgetBodyProps & { metric: string }) {
  const q = useRiskWindow()
  const item = q.data?.items.find(i => i.key === metric)
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!item || item.value == null) return <WidgetState empty emptyText={item?.error ? `수집 실패: ${item.error}` : "이 지표의 관측이 아직 없어요."} />
  return <div className="flex h-full flex-col gap-1.5">
    <WidgetHero value={riskValue(item.unit, item.value)} aside={<span className={cn("text-xs tabular-nums", tone(item.change_20))}>20일 {riskChange(item.unit, item.change_20)}</span>} />
    {item.quality !== "fresh" && <p className="text-[11px] text-chart-warning">{item.quality === "stale" ? `${item.lag_days ?? "?"}일 지연` : "수집 오류"}</p>}
    {h > 2 && <div className="mt-auto"><SparkLine data={item.points.map(p => p[1])} height={Math.max(28, (h - 2) * 40)} /></div>}
  </div>
}

/** 리스크 위젯 상세 — Risk 모니터링 화면의 카드 그대로(기간·계열 선택 포함) */
export function RiskDetail({ kind }: { kind: RiskCardKind }) {
  const view = useRiskView()
  if (!view.data) return <Card className="p-6"><WidgetState loading={view.query.isLoading} error={view.query.isError} onRetry={() => void view.query.refetch()} /></Card>
  return <RiskCard view={view} kind={kind} />
}

/* ── 개인 투자 열기 Δ ── */
export function useRetailMeta(): WidgetMeta {
  const q = useRetailSummary()
  return { asOf: q.data?.as_of ?? null }
}
export function RetailBody({ h }: WidgetBodyProps) {
  const q = useRetailSummary()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const moved = [...d.metrics].filter(m => m.pctile_change != null).sort((a, b) => Math.abs(b.pctile_change!) - Math.abs(a.pctile_change!))
  const top = moved[0]
  if (!top) return <WidgetState empty emptyText="개인 투자 지표가 아직 없어요." />
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${formatBp(top.pctile_change, true)}p`} aside={<span className="text-sm text-muted-foreground">{top.label}</span>} />
    <p className="text-[13px] text-muted-foreground">20일 새 백분위가 가장 크게 움직였어요 · 국면 <span className="font-medium text-foreground">{d.regime?.label ?? "-"}</span></p>
    {h > 3 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {moved.slice(1, 4).map(m => <li key={m.key} className="flex justify-between gap-2 py-1"><span className="truncate">{m.label}</span><span className="tabular-nums text-muted-foreground">{formatBp(m.pctile, false)}p ({formatBp(m.pctile_change, true)})</span></li>)}
    </ul>}
  </div>
}
