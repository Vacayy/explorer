import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import MultiLineChart from "@/components/charts/MultiLineChart"
import type { LineConfig } from "@/components/charts/MultiLineChart"
import AreaSeriesChart from "@/components/charts/AreaSeriesChart"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/**
 * 리포트 차트 (BACKLOG 리포트 차트/시각자료) — Top-pick 집중(D-047).
 * ① 상방/하방 비대칭 bar(전 종목) ② Top-pick 주가+이동평균 ③ Top-pick 12M Fwd PER 추이(D-046).
 *
 * ★항상 라이트: lightweight-charts 색은 라이트 고정인데 배경이 transparent라 다크에선 깨진다.
 *   그래서 이 블록 전체를 흰 배경 + 고정색(semantic 토큰 금지 — 다크에서 반전돼 흰 배경 위 안 보임)으로
 *   두어 다크/라이트 동일하게 보이게 한다.
 */
interface Stock { code: string; name: string; rating?: string; upside_pct?: number | null; downside_pct?: number | null }

export function ReportCharts({ stocks, topPick }: { stocks: Stock[]; topPick?: string | null }) {
  const top = stocks.find((s) => s.code === topPick) ?? stocks[0]
  const hasBar = stocks.some((s) => s.upside_pct != null || s.downside_pct != null)
  if (!hasBar && !top) return null

  return (
    <div className="space-y-4 rounded-lg border border-neutral-200 bg-white p-3 text-neutral-800">
      {hasBar && <UpsideDownsideBars stocks={stocks} topPick={topPick} />}
      {top && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <PriceChart code={top.code} name={top.name} />
          <FwdPerChart code={top.code} name={top.name} />
        </div>
      )}
    </div>
  )
}

/* ① 상방/하방 비대칭 — 하방(파랑, 왼쪽) ← 0 → 상방(빨강, 오른쪽). 고정색(한국 컨벤션 상방=빨강). */
function UpsideDownsideBars({ stocks, topPick }: { stocks: Stock[]; topPick?: string | null }) {
  const rows = stocks.filter((s) => s.upside_pct != null || s.downside_pct != null)
  const scale = Math.max(30, ...rows.map((s) => Math.max(Math.abs(s.downside_pct ?? 0), s.upside_pct ?? 0)))
  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold text-neutral-500">상방 / 하방 비대칭 (하방 대비 상방)</h4>
      <div className="space-y-1.5">
        {rows.map((s) => {
          const up = Math.max(0, s.upside_pct ?? 0)
          const down = Math.abs(Math.min(0, s.downside_pct ?? 0))
          const isTop = s.code === topPick
          return (
            <div key={s.code} className="flex items-center gap-2 text-[11px]">
              <span className={cn("w-20 shrink-0 truncate text-right", isTop ? "font-semibold text-neutral-900" : "text-neutral-700")}>{s.name}</span>
              <div className="flex flex-1 items-center">
                <div className="flex w-1/2 justify-end">
                  <div className="h-3.5 rounded-l bg-blue-400" style={{ width: `${(down / scale) * 100}%` }} />
                </div>
                <div className="h-4 w-px bg-neutral-300" />
                <div className="flex w-1/2 justify-start">
                  <div className="h-3.5 rounded-r bg-red-400" style={{ width: `${(up / scale) * 100}%` }} />
                </div>
              </div>
              <span className="w-24 shrink-0 tabular-nums">
                <span className="text-blue-500">{down ? `-${Math.round(down)}%` : "-"}</span>
                <span className="text-neutral-400">{" / "}</span>
                <span className="text-red-500">{up ? `+${Math.round(up)}%` : "-"}</span>
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

/* ② Top-pick 주가 + 이동평균(20·60) */
const PRICE_LINES: LineConfig[] = [
  { key: "close", label: "종가", color: "#374151", lineWidth: 2 },
  { key: "ma20", label: "MA20", color: "#3b82f6", lineWidth: 1 },
  { key: "ma60", label: "MA60", color: "#eab308", lineWidth: 1 },
]
interface PriceItem { trade_date: string; close: number }

function PriceChart({ code, name }: { code: string; name: string }) {
  const { data, isLoading } = useQuery(
    apiQuery<{ items: PriceItem[] }>({ key: ["prices", code, "report"], url: `/api/stock-prices/${code}`, params: { from_date: "20260101" }, staleTime: STALE.medium }),
  )
  const items = data?.items ?? []
  const rows = items.map((p, i) => ({
    time: p.trade_date, close: p.close,
    ma20: i >= 19 ? avg(items.slice(i - 19, i + 1)) : null,
    ma60: i >= 59 ? avg(items.slice(i - 59, i + 1)) : null,
  }))
  return (
    <ChartBox title={`${name} 주가 · 이동평균`}>
      {isLoading ? <Skeleton className="h-[240px] w-full" />
        : rows.length === 0 ? <Empty msg="주가 데이터 없음" />
        : <MultiLineChart data={rows} lines={PRICE_LINES} height={240} formatValue={(v) => v.toLocaleString()} />}
    </ChartBox>
  )
}
const avg = (xs: PriceItem[]) => xs.reduce((s, x) => s + x.close, 0) / xs.length

/* ③ Top-pick 12M Fwd PER 추이 (이력 얕으면 안내) */
function FwdPerChart({ code, name }: { code: string; name: string }) {
  const { data, isLoading } = useQuery(
    apiQuery<{ items: { date: string; fwd_per: number }[] }>({ key: ["consensus", code, "history"], url: `/api/consensus/${code}/history`, staleTime: STALE.medium }),
  )
  const items = (data?.items ?? []).filter((d) => d.fwd_per != null)
  const series = items.map((d) => ({ time: d.date, value: d.fwd_per }))
  return (
    <ChartBox title={`${name} 12M Fwd PER 추이`}>
      {isLoading ? <Skeleton className="h-[240px] w-full" />
        : series.length < 3 ? <Empty msg="컨센서스 이력 축적 중 (매일 스냅샷)" />
        : <AreaSeriesChart data={series} height={240} formatValue={(v) => `${v.toFixed(1)}배`} />}
    </ChartBox>
  )
}

function ChartBox({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-200 p-3">
      <h4 className="mb-2 text-xs font-semibold text-neutral-500">{title}</h4>
      {children}
    </div>
  )
}
function Empty({ msg }: { msg: string }) {
  return <div className="flex h-[240px] items-center justify-center text-xs text-neutral-400">{msg}</div>
}
