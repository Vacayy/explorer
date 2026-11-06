import { Link, useParams } from "react-router-dom"
import { PageLayout } from "@/components/shared/PageLayout"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { BigChart, DialogRow, MonitorDialog, StatGrid, type BigPoint, type Stat } from "@/components/industry/MonitorWall"
import { useTwRevenue } from "@/hooks/useTwRevenue"
import { cn } from "@/lib/utils"
import { formatPercent, formatTwdEok } from "@/utils/format"
import type { TwRevenueItem } from "@/types"

/**
 * 대만 회사 월매출 상세 — 가운데 대화상자(TaiwanPage, URL tw)와 상세 페이지(/follow/taiwan/:code)가 같은 내용을 쓴다(D-325).
 * 36개월 매출 막대 + 전년 대비 선 · 전월 대비 · 3개월 전년 대비 · 공시 상태 · 계층 · 역할(+ 회사가 밝힌 증감 사유).
 * 원천은 /tw/revenue 하나(36개월 시계열 포함) — 새 API 없음.
 */

/** 기준 = 가장 최근 공시 월. 매달 10일이 지나도 전전월이면 수집이 멈춘 것 */
export function twStale(asOf: string | null): boolean {
  if (!asOf) return false
  const now = new Date(), [y, m] = asOf.split("-").map(Number)
  const lag = (now.getFullYear() - y) * 12 + (now.getMonth() + 1 - m)
  return lag > 2 || (lag === 2 && now.getDate() > 11)
}

type Layers = { key: string; label: string }[]
const layerOf = (item: TwRevenueItem, layers: Layers) => layers.find(l => l.key === item.layer)?.label ?? item.layer
const points = (item: TwRevenueItem): BigPoint[] => item.series.map(p => ({ period: p.ym, v: p.revenue, yoy: p.yoy_pct }))
const value = (item: TwRevenueItem) => `${formatTwdEok(item.revenue)} TWD${item.ym ? ` · ${+item.ym.slice(5, 7)}월` : ""}`
const fmtTwd = (v: number) => `${formatTwdEok(v)} TWD`

function stats(item: TwRevenueItem, layers: Layers, asOf: string | null): Stat[] {
  return [
    { label: "전월 대비", value: formatPercent(item.mom_pct), tone: item.mom_pct },
    { label: "3개월 전년 대비", value: formatPercent(item.yoy_3m), tone: item.yoy_3m },
    { label: "공시", value: item.lagging ? `지연 · ${item.ym?.slice(5) ?? "-"}월분` : `${asOf ? +asOf.slice(5, 7) : "-"}월 반영` },
    { label: "계층", value: layerOf(item, layers) },
  ]
}

export function TwCompanyDialog({ code, item, layers, asOf, onClose }: { code: string | null; item?: TwRevenueItem; layers: Layers; asOf: string | null; onClose: () => void }) {
  if (!code || !item) return null
  return <MonitorDialog open onClose={onClose} sub={`${layerOf(item, layers)} · ${item.code}`} name={item.name} value={value(item)} yoy={item.yoy_pct}
    detailTo={`/follow/taiwan/${encodeURIComponent(item.code)}`}>
    <BigChart data={points(item)} barLabel="월매출(36개월)" fmt={fmtTwd} />
    <StatGrid stats={stats(item, layers, asOf)} />
    <DialogRow label="역할">{item.role || "-"}</DialogRow>
  </MonitorDialog>
}

/** 상세 페이지 /follow/taiwan/:code — 대화상자와 같은 내용을 크게 */
export default function TaiwanCompanyPage() {
  const { code = "" } = useParams()
  const q = useTwRevenue()
  const d = q.data
  const item = d?.items.find(i => i.code === code)
  if (q.isError && !d) return <PageLayout mode="document"><ErrorState message="대만 월매출을 불러오지 못했습니다." onRetry={() => void q.refetch()} /></PageLayout>
  if (d && !item) return <PageLayout mode="document"><EmptyState message="이 회사의 월매출이 없습니다." /><Link to="/follow/taiwan" className="text-[13px] text-ink-2 hover:text-ink">‹ 대만 공급망</Link></PageLayout>
  return <PageLayout mode="document">
    <div className="flex flex-col gap-5">
      <Link to="/follow/taiwan" className="w-fit text-[13px] text-ink-2 hover:text-ink">‹ 대만 공급망</Link>
      {!item || !d ? <div role="status" aria-label="불러오는 중" className="flex flex-col gap-3"><Skeleton className="h-4 w-40" /><Skeleton className="h-9 w-64" /><Skeleton className="h-[460px] w-full" /></div> : <>
        <header className="flex flex-col gap-1">
          <span className="text-[13px] text-ink-3">{layerOf(item, d.layers)} · {item.code} · {item.market === "TPEx" ? "장외" : "상장"}</span>
          <h1 className="font-display text-page font-normal tracking-[-0.02em] max-md:text-[26px]">{item.name}</h1>
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="font-display text-[32px] leading-tight tabular-nums">{value(item)}</span>
            <span className={cn("font-mono text-base tabular-nums", (item.yoy_pct ?? 0) > 0 ? "text-up-ink" : (item.yoy_pct ?? 0) < 0 ? "text-down-ink" : "text-ink-2")}>전년 대비 {formatPercent(item.yoy_pct)}</span>
          </div>
        </header>
        <section className="flex flex-col gap-4 border bg-card p-5 max-sm:p-3">
          <BigChart data={points(item)} height={360} barLabel="월매출(36개월)" fmt={fmtTwd} />
          <StatGrid stats={stats(item, d.layers, d.as_of)} large />
        </section>
        <section className="flex flex-col gap-3 border bg-card p-5 max-sm:p-3">
          <DialogRow label="역할">{item.role || "-"}</DialogRow>
          {item.note && <DialogRow label={`회사가 밝힌 증감 사유(${item.ym})`}>{item.note}</DialogRow>}
        </section>
      </>}
    </div>
  </PageLayout>
}
