import { useMemo } from "react"
import RegimeChart from "@/components/charts/RegimeChart"
import { BrkControls, brkBands, brkSeries, tone, useBrkParams } from "@/components/regimes/BrkPanel"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { useBrk } from "@/hooks/useRegimes"
import { cn } from "@/lib/utils"
import { formatPp } from "@/utils/format"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/* 국면 이력 위젯 (docs/specs/market-regimes.md §6) — 버크셔 vs 지수 5년, 약세장·침체 음영. 벤치·보기는 페이지와 같은 URL 상태 */

function useBrkMeta(): WidgetMeta {
  const p = useBrkParams("5y")
  const q = useBrk(p.bench, "5y")
  return { asOf: q.data?.as_of ?? null }
}

function BrkBody({ w, h }: WidgetBodyProps) {
  const p = useBrkParams("5y")
  const q = useBrk(p.bench, "5y")
  const d = q.data
  const series = useMemo(() => d ? brkSeries(d, p.view) : [], [d, p.view])
  const bands = useMemo(() => d ? brkBands(d) : [], [d])
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.points.length) return <WidgetState empty emptyText="시세 이력이 아직 없어요. 탐색 › 국면 이력에서 수집하세요." />
  const last = d.rolling.at(-1)
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={<span className={tone(last?.excess_12m)}>{formatPp(last?.excess_12m, 1)}</span>}
      aside={<span className="text-xs text-muted-foreground">12개월 BRK − {d.bench.label}</span>} />
    {w >= 4 && <BrkControls {...p} ranges={false} />}
    {h > 3 && <div className="min-h-0 flex-1">
      <RegimeChart series={series} bands={bands} height={Math.max(110, h * 72 - (w >= 4 ? 170 : 120))}
        formatValue={v => p.view === "spread" ? v.toFixed(0) : `${v.toFixed(0)}%`} />
    </div>}
    {!d.bench.dividends && <p className={cn("text-[11px] text-muted-foreground")}>배당 제외 지수 — BRK가 다소 유리하게 보입니다</p>}
  </div>
}

export const REGIME_WIDGETS: WidgetDef[] = [
  { id: "explore.brk", title: "버크셔 vs 지수", description: "BRK.B와 S&P500·나스닥 5년 비교·상대강도 · 약세장 음영",
    section: "explore", group: "국면 이력", size: { w: 6, h: 5, minW: 3, minH: 2 }, detailPath: "/home/macro#brk",
    useMeta: useBrkMeta, Body: BrkBody },
]
