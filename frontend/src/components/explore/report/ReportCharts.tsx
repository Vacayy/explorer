import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { formatPer, formatWonShort } from "@/utils/format"

/**
 * 리포트 차트 (BACKLOG 리포트 차트/시각자료) — Top-pick 집중(D-047).
 * ① 상방/하방 비대칭 bar(전 종목) ② Top-pick 주가 ③ Top-pick 12M Fwd PER 추이(D-046).
 * ②③은 시안 Report대로 작은 선 차트 두 개 나란히 — 글자색 선 하나 + 리포트 작성일 점선·점.
 */
interface Stock { code: string; name: string; rating?: string; upside_pct?: number | null; downside_pct?: number | null }

export function ReportCharts({ stocks, topPick, reportDate }: { stocks: Stock[]; topPick?: string | null; reportDate?: string | null }) {
  const top = stocks.find((s) => s.code === topPick) ?? stocks[0]
  const hasBar = stocks.some((s) => s.upside_pct != null || s.downside_pct != null)
  if (!hasBar && !top) return null

  return (
    <div className="border-b pb-4 space-y-4">
      {hasBar && <UpsideDownsideBars stocks={stocks} topPick={topPick} />}
      {top && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <PriceChart code={top.code} name={top.name} reportDate={reportDate} />
          <FwdPerChart code={top.code} name={top.name} reportDate={reportDate} />
        </div>
      )}
    </div>
  )
}

/* ① 상방/하방 비대칭 — 하방(파랑, 왼쪽) ← 0 → 상방(빨강, 오른쪽). 한국 컨벤션 상방=빨강. */
function UpsideDownsideBars({ stocks, topPick }: { stocks: Stock[]; topPick?: string | null }) {
  const rows = stocks.filter((s) => s.upside_pct != null || s.downside_pct != null)
  const scale = Math.max(30, ...rows.map((s) => Math.max(Math.abs(s.downside_pct ?? 0), s.upside_pct ?? 0)))
  return (
    <section>
      <h4 className="text-xs font-semibold text-muted-foreground mb-2">상방 / 하방 비대칭 (하방 대비 상방)</h4>
      <div className="space-y-1.5">
        {rows.map((s) => {
          const up = Math.max(0, s.upside_pct ?? 0)
          const down = Math.abs(Math.min(0, s.downside_pct ?? 0))
          const isTop = s.code === topPick
          return (
            <div key={s.code} className="flex items-center gap-2 text-[11px]">
              <span className={cn("w-20 shrink-0 truncate text-right", isTop && "font-semibold text-primary")}>{s.name}</span>
              <div className="flex flex-1 items-center">
                <div className="flex w-1/2 justify-end">
                  <div className="h-3.5 rounded-l bg-down" style={{ width: `${(down / scale) * 100}%` }} />
                </div>
                <div className="h-4 w-px bg-border" />
                <div className="flex w-1/2 justify-start">
                  <div className="h-3.5 rounded-r bg-up" style={{ width: `${(up / scale) * 100}%` }} />
                </div>
              </div>
              <span className="w-24 shrink-0 tabular-nums text-muted-foreground">
                <span className="text-down-ink">{down ? `-${Math.round(down)}%` : "-"}</span>
                {" / "}
                <span className="text-up-ink">{up ? `+${Math.round(up)}%` : "-"}</span>
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

/* ② Top-pick 주가 */
export interface PriceItem { trade_date: string; close: number }

/** Top-pick 주가(올해) — 차트와 리포트 '작성 이후' 줄이 같은 조회를 쓴다 */
export function useReportPrices(code: string | null | undefined) {
  return useQuery(
    apiQuery<{ items: PriceItem[] }>({ key: ["prices", code, "report"], url: `/api/stock-prices/${code}`, params: { from_date: "20260101" }, staleTime: STALE.medium, enabled: !!code }),
  )
}

/** Top-pick 12M Fwd PER 이력 — 차트와 '작성 이후' 줄 공용 */
export function useReportFwdPer(code: string | null | undefined) {
  return useQuery(
    apiQuery<{ items: { date: string; fwd_per: number }[] }>({ key: ["consensus", code, "history"], url: `/api/consensus/${code}/history`, staleTime: STALE.medium, enabled: !!code }),
  )
}

const md = (d: string) => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`

function PriceChart({ code, name, reportDate }: { code: string; name: string; reportDate?: string | null }) {
  const { data, isLoading } = useReportPrices(code)
  const points = (data?.items ?? []).map((p) => ({ date: p.trade_date.slice(0, 10), value: p.close }))
  const title = `${name} 주가${points.length ? ` · ${md(points[0].date)}~${md(points[points.length - 1].date)}` : ""}`
  return (
    <ChartBox title={title}>
      {isLoading ? <Skeleton className="aspect-[400/170] w-full" />
        : points.length < 2 ? <Empty msg="주가 데이터 없음" />
        : <MiniLine points={points} label={title} marker={reportDate} format={formatWonShort} />}
    </ChartBox>
  )
}

/* ③ Top-pick 12M Fwd PER 추이 (이력 얕으면 안내) */
function FwdPerChart({ code, name, reportDate }: { code: string; name: string; reportDate?: string | null }) {
  const { data, isLoading } = useReportFwdPer(code)
  const points = (data?.items ?? []).filter((d) => d.fwd_per != null).map((d) => ({ date: d.date.slice(0, 10), value: d.fwd_per }))
  const title = `${name} 12개월 선행 PER${points.length ? ` · ${md(points[0].date)}~${md(points[points.length - 1].date)}` : ""}`
  return (
    <ChartBox title={title}>
      {isLoading ? <Skeleton className="aspect-[400/170] w-full" />
        : points.length < 3 ? <Empty msg="컨센서스 이력 축적 중 (매일 스냅샷)" />
        : <MiniLine points={points} label={title} marker={reportDate} format={formatPer} />}
    </ChartBox>
  )
}

/** 시안 Report 작은 선 차트(400×170): 왼쪽 눈금 4개·격자, 글자색 선 1.6, 리포트 날짜 점선 + 점 + 'M/D 리포트', x 처음·가운데·끝 */
function MiniLine({ points, label, marker, format }: { points: { date: string; value: number }[]; label: string; marker?: string | null; format: (v: number) => string }) {
  const L = 52, R = 392, T = 18, B = 140
  const vs = points.map((p) => p.value)
  const lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1
  const x = (i: number) => L + (i / (points.length - 1)) * (R - L)
  const y = (v: number) => B - ((v - lo) / span) * (B - T)
  const ticks = [0, 1, 2, 3].map((k) => lo + (span * k) / 3)
  const mi = marker ? points.findIndex((p) => p.date >= marker.slice(0, 10)) : -1
  const mid = Math.floor((points.length - 1) / 2)
  return (
    <svg viewBox="0 0 400 170" role="img" aria-label={label} className="block h-auto w-full">
      {ticks.map((v) => <g key={v}><line x1={L} x2={R} y1={y(v)} y2={y(v)} stroke="var(--grid)" /><text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize={10.5} fill="var(--ink-3)">{format(v)}</text></g>)}
      <path d={points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ")} fill="none" stroke="var(--ink)" strokeWidth={1.6} />
      {mi >= 0 && <>
        <line x1={x(mi)} x2={x(mi)} y1={10} y2={148} stroke="var(--ink-3)" strokeDasharray="3 3" />
        <circle cx={x(mi)} cy={y(points[mi].value)} r={3.5} fill="var(--surface)" stroke="var(--ink)" strokeWidth={1.5} />
        <text x={x(mi) + (x(mi) > 320 ? -6 : 6)} y={20} textAnchor={x(mi) > 320 ? "end" : "start"} fontSize={10.5} fill="var(--ink-2)">리포트 {md(marker!)}</text>
      </>}
      <text x={L} y={164} fontSize={10.5} fill="var(--ink-3)">{md(points[0].date)}</text>
      <text x={x(mid)} y={164} textAnchor="middle" fontSize={10.5} fill="var(--ink-3)">{md(points[mid].date)}</text>
      <text x={R} y={164} textAnchor="end" fontSize={10.5} fill="var(--ink-3)">{md(points[points.length - 1].date)}</text>
    </svg>
  )
}

function ChartBox({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-ink-3">{title}</span>
      {children}
    </div>
  )
}
function Empty({ msg }: { msg: string }) {
  return <div className="flex aspect-[400/170] items-center justify-center bg-surface-2 text-xs text-muted-foreground">{msg}</div>
}
