import type { ReactNode } from "react"
import { Badge } from "@/components/ui/badge"
import { MetricTrend } from "@/components/shared/MetricTrend"
import { AreaSpark, SparkLine } from "@/components/shared/Spark"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { fmtValue } from "@/components/home/MacroLiquidity"
import { UsBriefingSection } from "@/components/home/UsBriefingSection"
import { useIndices, useRiskWindow } from "@/hooks/useDashboard"
import { useMacro } from "@/hooks/useMacro"
import { useMarketRegime } from "@/hooks/useMarketRegime"
import { useUsBriefing } from "@/hooks/useUsBriefing"
import { fearGreedZone } from "@/lib/macroPage"
import { cn } from "@/lib/utils"
import { formatBp, formatLevel, formatPercent, formatRatio, formatYield } from "@/utils/format"
import type { WidgetBodyProps, WidgetMeta } from "./types"

/**
 * 시장 위젯 10종 — 요약층만 (docs/specs/home-widgets.md §3). 모두 캐시된 GET 훅만 읽고 갱신 버튼은 전체 보기 탭에 둔다.
 * 각 위젯은 { meta(기준 시각·고장), body }를 돌려주는 훅 + 본문 컴포넌트 한 쌍이다.
 */

const tone = (v: number | null | undefined) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up-ink" : "text-down-ink"

/* ── 지수 띠 ── */
export function useIndicesMeta(): WidgetMeta {
  const q = useIndices()
  return { asOf: q.data?.as_of ?? null, stale: !!q.data?.degraded.length }
}
export function IndicesBody(_: WidgetBodyProps) {
  const q = useIndices()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  // 시안 Home 지수 띠 — 칸 최소 132px, 넘치면 띠 안에서 가로로 민다. 점: 장중 = 사실(초록) · 마감 = --closed
  return <div className="grid h-full auto-cols-[minmax(132px,1fr)] grid-flow-col overflow-x-auto overscroll-x-contain">
    {q.data.items.map(r => (
      <div key={r.key} className="flex min-w-0 flex-col gap-1 border-r border-glass-line px-3.5 py-3 last:border-r-0">
        <span className="flex items-center justify-between gap-1.5 text-xs">
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <span title={r.is_open ? "장중" : "마감"} aria-label={r.is_open ? "장중" : "마감"} className={cn("size-[7px] flex-none rounded-full", r.is_open ? "bg-fact shadow-[0_0_0_3px_var(--fact-tint)]" : "bg-closed")} />
            <span className="truncate">{r.label}</span>
          </span>
          <span className={cn("shrink-0 font-mono tabular-nums", tone(r.change_pct))}>{formatPercent(r.change_pct)}</span>
        </span>
        <span className="truncate font-mono text-[17px] tabular-nums">{formatLevel(r.price)}</span>
        {/* 1Y 추이 */}
        <div className="h-5"><SparkLine data={r.spark} height={20} className="h-full w-full" /></div>
      </div>
    ))}
  </div>
}

/* ── 시장 요약 띠 ── */
// 홈 관찰 목록 — 비트코인은 2026-11-03 제외(매크로 화면에는 그대로)
const CONTEXT_KEYS = ["usdkrw", "jpykrw", "us2y", "us10y", "oil", "gold"]
export function useContextMeta(): WidgetMeta {
  const q = useMacro()
  return { asOf: q.data?.as_of ?? null, stale: !!q.data?.degraded.length }
}
export function ContextBody(_: WidgetBodyProps) {
  const q = useMacro()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const items = CONTEXT_KEYS.map(k => q.data!.items.find(i => i.key === k)).filter(Boolean) as NonNullable<typeof q.data>["items"]
  // 시안 Home 시장 요약 띠 — 한 줄(라벨 · 값 · 변동), 넘치면 띠 안에서 가로로 민다
  return <div className="flex overflow-x-auto overscroll-x-contain">
    {items.map(m => (
      // 올리면(클릭·키보드도) 추이 차트 — 시장 브리핑 지표 띠와 같은 MetricTrend
      <MetricTrend key={m.key} label={m.label} points={m.dated_series} format={v => fmtValue({ ...m, value: v })}
        className="h-auto shrink-0 items-baseline gap-2 rounded-none border-r border-glass-line px-3.5 py-2 text-left font-normal whitespace-nowrap last:border-r-0 hover:bg-transparent hover:opacity-75">
        <span className="text-xs opacity-85">{m.label}</span>
        <span className="font-mono text-[13.5px] tabular-nums">{fmtValue(m)}</span>
        <span className={cn("font-mono text-xs tabular-nums", tone(m.change_pct))}>{formatPercent(m.change_pct)}</span>
      </MetricTrend>
    ))}
  </div>
}

/* ── 어젯밤 미국장 ── */
export function useUsMeta(): WidgetMeta {
  const q = useUsBriefing(null)
  const d = q.data
  // 머리 = 반영한 미국 장 날짜. 어젯밤 장이 아니거나 정기 생성이 실패했으면 주의 색
  const missed = !!d?.expected_session && d.trade_date !== d.expected_session
  return { asOf: d?.trade_date ?? null, stale: !!d && (d.status !== "ok" || missed || (!!d.last_run && d.last_run.status !== "ok")) }
}
/** 넉넉한 위젯 — 원래 섹션 전체를 위젯 안에서 스크롤 (요약은 작게 줄였을 때만) */
function Full({ children }: { children: ReactNode }) {
  return <div className="@container/market -mr-2 h-full overflow-y-auto pr-2">{children}</div>
}
export function UsBody({ h }: WidgetBodyProps) {
  return h > 3 ? <Full><UsBriefingSection embedded /></Full> : <UsSummary h={h} />
}
function UsSummary({ h }: { h: number }) {
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

/* ── 시장 국면 ── */
export function useRegimeMeta(): WidgetMeta {
  const q = useMarketRegime()
  return { asOf: q.data?.as_of ?? null, stale: !!q.data?.degraded.length }
}
/** 포스처 칩 색 — 시안 Home: 중립 회색 · 보류(주의) 파랑 틴트 · 위험 노랑 · 우호 분홍 */
const POSTURE_VARIANT: Record<string, "neutral" | "down" | "warn" | "up"> = { neutral: "neutral", caution: "down", risk: "warn", favorable: "up" }
export function RegimeBody({ h }: WidgetBodyProps) {
  const q = useMarketRegime()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.kr && !d.us) return <WidgetState empty emptyText="국면 판정 재료가 아직 없어요." />
  return <div className="flex h-full flex-col gap-2">
    <div className="flex flex-wrap items-center gap-2.5">
      {d.kr && <Badge variant={POSTURE_VARIANT[d.kr.posture_color] ?? "neutral"}>국장 {d.kr.posture}</Badge>}
      {d.us && <Badge variant={POSTURE_VARIANT[d.us.posture_color] ?? "neutral"}>미장 {d.us.posture}</Badge>}
      <span className={cn("min-w-0 text-[13px]", h <= 2 ? "line-clamp-1" : "line-clamp-2")}>{d.headline}</span>
    </div>
    {h > 2 && <div className="grid grid-cols-2 gap-2">
      <Tile label="공포탐욕" value={d.us?.fear_greed ? formatLevel(d.us.fear_greed.score) : "-"} sub={d.us?.fear_greed?.zone} />
      <Tile label="VIX" value={d.us?.vix ? formatLevel(d.us.vix.value) : "-"} sub={d.us?.vix?.band} />
    </div>}
    {d.degraded.length > 0 && <p className="text-[11px] text-warn">빠진 재료: {d.degraded.join(", ")}</p>}
  </div>
}
function Tile({ label, value, sub }: { label: string; value: string; sub?: string | null }) {
  return <div className="rounded-lg bg-muted/60 px-2.5 py-1.5"><div className="text-[11px] text-muted-foreground">{label}</div>
    <div className="text-base font-semibold tabular-nums">{value}</div>{sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}</div>
}

/* ── Risk 단일 지표 ── */
export function riskValue(unit: string, v: number | null) {
  return unit === "%" ? formatYield(v) : unit === "bp" ? (v == null ? "-" : `${formatBp(v)}bp`) : formatLevel(v)
}
export function riskChange(unit: string, v: number | null) {
  if (v == null) return "-"
  return unit === "bp" ? `${formatBp(v, true)}bp` : unit === "%" ? `${formatBp(v * 100, true)}bp` : `${v > 0 ? "+" : ""}${formatLevel(v)}`
}
export function useRiskMeta(key: string): WidgetMeta {
  const q = useRiskWindow()
  const item = q.data?.items.find(i => i.key === key)
  return { asOf: item?.as_of ?? null, stale: !!item && item.quality !== "fresh" }
}
/** 3개월 추이 기준선 — VIX 20 · 공포탐욕 50 (시안 Home) */
const RISK_REF: Record<string, number> = { vix: 20, fear_greed: 50 }
const md = (d: string | null | undefined) => (d ? d.slice(5, 10).replace("-", "/") : "")

/**
 * 국면·리스크 타일(시안 Home) — 이름 · 기준일 / 값(mono 19) / 20일 변화 / 3개월 회색 추이(기준선 점선·끝점) / 처음·끝 날짜.
 * 갱신 실패·지연이면 마지막 값을 흐리게 두고 지연을 붙인다 — 숫자를 지우지 않는다 (ia-redesign §4.28).
 */
export function RiskTrend({ metric, label, className }: { metric: string; label: string; className?: string }) {
  const q = useRiskWindow()
  const item = q.data?.items.find(i => i.key === metric)
  const head = (date?: string | null) => <div className="flex items-baseline gap-2"><span className="text-xs text-ink-3">{label}</span>{date && <span className="ml-auto text-[11px] text-ink-3">{md(date)}</span>}</div>
  if (!q.data) return <div className={cn("flex min-w-0 flex-col gap-0.5 py-2.5 pr-3.5", className)}>{head()}<WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} /></div>
  if (!item || item.value == null) return <div className={cn("flex min-w-0 flex-col gap-0.5 py-2.5 pr-3.5", className)}>{head()}<WidgetState empty emptyText={item?.error ? `수집 실패: ${item.error}` : "이 지표의 관측이 아직 없어요."} /></div>
  const fresh = item.quality === "fresh"
  const pts = item.points
  return <div className={cn("flex min-w-0 flex-col gap-0.5 pt-2.5 pr-3.5 pb-1.5", className)} data-risk-tile={metric}>
    {head(item.as_of)}
    <div className={cn("flex flex-col gap-0.5", !fresh && "opacity-60")}>
      <span className="font-mono text-[19px] tabular-nums">{riskValue(item.unit, item.value)}</span>
      <span className="text-xs text-ink-2">{metric === "fear_greed" && fearGreedZone(item.value) ? `${fearGreedZone(item.value)} · ` : ""}20일 <span className={cn("font-mono tabular-nums", tone(item.change_20))}>{riskChange(item.unit, item.change_20)}</span></span>
    </div>
    {!fresh && <p className="text-[11px] text-warn">{item.quality === "stale" ? `${item.lag_days ?? "?"}일 지연` : "갱신 실패"}</p>}
    {pts.length > 1 && <>
      <div className={cn("mt-1.5", !fresh && "opacity-60")}>
        <AreaSpark data={pts.map(p => p[1])} refValue={RISK_REF[metric]} label={`${label} 3개월 추이, ${pts[0][0]}부터 ${pts[pts.length - 1][0]}까지`} />
      </div>
      <div className="flex justify-between font-mono text-[10.5px] text-ink-3 tabular-nums"><span>{md(pts[0][0])}</span><span>{md(pts[pts.length - 1][0])}</span></div>
    </>}
  </div>
}

export function RiskBody({ metric, h }: WidgetBodyProps & { metric: string }) {
  const q = useRiskWindow()
  const item = q.data?.items.find(i => i.key === metric)
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!item || item.value == null) return <WidgetState empty emptyText={item?.error ? `수집 실패: ${item.error}` : "이 지표의 관측이 아직 없어요."} />
  // 갱신 실패·지연이면 마지막 값을 흐리게 두고 기준 날짜를 붙인다 — 숫자를 지우지 않는다 (ia-redesign §4.28)
  const fresh = item.quality === "fresh"
  const day = item.as_of ? item.as_of.slice(5, 10).replace("-", "/") : null
  return <div className="flex h-full flex-col gap-1.5">
    <WidgetHero className={cn(!fresh && "opacity-60")} value={riskValue(item.unit, item.value)} aside={<span className={cn("text-xs tabular-nums", tone(item.change_20))}>20일 {riskChange(item.unit, item.change_20)}</span>} />
    {!fresh && <p className="text-[11px] text-chart-warning">{item.quality === "stale" ? `${item.lag_days ?? "?"}일 지연` : "갱신 실패"}{day ? ` · ${day} 값` : ""}</p>}
    {h > 2 && <div className="mt-auto"><SparkLine data={item.points.map(p => p[1])} height={Math.max(28, (h - 2) * 40)} /></div>}
  </div>
}
