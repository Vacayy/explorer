import { Fragment, useMemo } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { PageLayout } from "@/components/shared/PageLayout"
import { ErrorState } from "@/components/shared/ErrorState"
import { BlockError } from "@/components/home/blockState"
import { BigChart, DialogRow, MonitorDialog, StatGrid, type BigPoint, type Stat } from "@/components/industry/MonitorWall"
import { useTradeGrid } from "@/hooks/useTrade"
import { yoySeries } from "@/lib/trade"
import { cn } from "@/lib/utils"
import { formatPercent, formatRatio, formatUsd } from "@/utils/format"
import type { TradeGridItem } from "@/types"

/**
 * 수출입 품목 상세 — 가운데 대화상자(TradePage, URL hs)와 상세 페이지(/follow/trade/:hs)가 같은 내용을 쓴다(D-325).
 * 5년 월별 수출 막대 + 전년 대비 선 · 전월 대비 · 3개월 전년 대비 · 증가분 기여 · 평소 대비(z) · 관련 종목.
 * 시계열·관련 종목은 /trade/{hs}, 판정 숫자는 벽과 같은 /trade/grid 행(없으면 시계열로 계산, 기여·z는 '-').
 */
interface Stat0 { period: string; export_usd: number | null }
interface Beneficiary { name: string; stock_code: string | null; rel: string | null; reason: string | null; in_universe: boolean }
interface Detail { hs_code: string; item_name: string; series: Stat0[]; beneficiaries: Beneficiary[] }

const detailQuery = (hs: string) => apiQuery<Detail>({ key: ["spine", "trade", hs], url: `/api/spine/trade/${hs}`, staleTime: STALE.medium })
const ratio = (v: number | null | undefined) => formatPercent(v == null ? null : v * 100)

function computed(series: Stat0[]) {
  const v = series.map(s => s.export_usd)
  const n = v.length - 1
  const sum = (a: number, b: number) => { const s = v.slice(a, b + 1); return s.length === b - a + 1 && s.every(x => x != null) ? (s as number[]).reduce((x, y) => x + y, 0) : null }
  const mom = n >= 1 && v[n] != null && v[n - 1] ? v[n]! / v[n - 1]! - 1 : null
  const now3 = n >= 14 ? sum(n - 2, n) : null, prev3 = n >= 14 ? sum(n - 14, n - 12) : null
  return { mom, yoy3m: now3 != null && prev3 ? now3 / prev3 - 1 : null }
}

function useTradeItem(hs: string, item?: TradeGridItem) {
  const q = useQuery(detailQuery(hs))
  const view = useMemo(() => {
    const d = q.data
    if (!d) return null
    const s = d.series.filter(p => p.export_usd != null)
    const yoy = yoySeries(s.map(p => p.export_usd))
    const points: BigPoint[] = s.map((p, i) => ({ period: p.period, v: p.export_usd, yoy: yoy[i] })).slice(-60)
    const last = s[s.length - 1]
    const c = computed(d.series)
    const mom = item?.mom ?? c.mom, yoy3m = item?.yoy3m ?? c.yoy3m
    const stats: Stat[] = [
      { label: "전월 대비", value: ratio(mom), tone: mom },
      { label: "3개월 전년 대비", value: ratio(yoy3m), tone: yoy3m },
      { label: "증가분 기여", value: formatRatio(item?.contribution == null ? null : item.contribution * 100) },
      { label: "평소 대비(z)", value: item?.z == null ? "-" : item.z.toFixed(1) },
    ]
    return { name: d.item_name, points, last, yoy: item?.yoy_pct ?? (yoy[yoy.length - 1] ?? null), stats, bene: d.beneficiaries }
  }, [q.data, item])
  return { q, view }
}

const monthOf = (period?: string) => period ? `${+period.slice(5, 7)}월` : ""
const sub = (hs: string, item?: TradeGridItem) => `${item?.group_label ?? "수출입"} · HS ${hs}`

/** 관련 종목 이름 줄 — 도시에 링크 */
function StockNames({ bene }: { bene: Beneficiary[] }) {
  if (!bene.length) return <span className="text-ink-3">아직 지목한 종목이 없습니다</span>
  return <span>{bene.map((b, i) => <Fragment key={`${b.name}${i}`}>{i > 0 && " · "}
    {b.stock_code ? <Link to={`/analyze/${b.stock_code}/summary`} className="hover:underline">{b.name}</Link> : b.name}
  </Fragment>)}</span>
}

export function TradeItemDialog({ hs, item, onClose }: { hs: string | null; item?: TradeGridItem; onClose: () => void }) {
  return hs ? <TradeDialogInner key={hs} hs={hs} item={item} onClose={onClose} /> : null
}

function TradeDialogInner({ hs, item, onClose }: { hs: string; item?: TradeGridItem; onClose: () => void }) {
  const { q, view } = useTradeItem(hs, item)
  const val = view?.last?.export_usd ?? item?.latest_export
  return <MonitorDialog open onClose={onClose} sub={sub(hs, item)} name={view?.name ?? item?.item_name ?? "품목 상세"}
    value={val == null ? "-" : `${formatUsd(val)} · ${monthOf(view?.last?.period ?? item?.latest_period ?? undefined)}`} yoy={view?.yoy ?? item?.yoy_pct ?? null}
    detailTo={`/follow/trade/${encodeURIComponent(hs)}`}>
    {view ? <>
      <BigChart data={view.points} barLabel="월별 수출액(5년)" fmt={formatUsd} />
      <StatGrid stats={view.stats} />
      <DialogRow label="관련 종목"><StockNames bene={view.bene.filter(b => b.rel !== "피해")} /></DialogRow>
    </> : q.isError ? <BlockError message="품목 추이를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : <div role="status" aria-label="불러오는 중" className="flex flex-col gap-4"><Skeleton className="h-[264px] w-full" /><Skeleton className="h-[60px] w-full" /><Skeleton className="h-10 w-2/3" /></div>}
  </MonitorDialog>
}

/** 상세 페이지 /follow/trade/:hs — 대화상자와 같은 내용을 크게 + 관련 종목 이유·다시 지목 */
export default function TradeItemPage() {
  const { hs = "" } = useParams()
  const grid = useTradeGrid(24)
  const item = grid.data?.items.find(i => i.hs_code === hs)
  const { q, view } = useTradeItem(hs, item)
  const qc = useQueryClient()
  const compute = useMutation({
    mutationFn: () => api.post(`/api/spine/trade/${hs}/beneficiaries`, null, { timeout: 300_000 }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "trade", hs] }),
  })
  if (q.isError && !q.data) return <PageLayout mode="document"><ErrorState message="품목을 불러오지 못했습니다." onRetry={() => void q.refetch()} /></PageLayout>
  const val = view?.last?.export_usd ?? null
  return <PageLayout mode="document">
    <div className="flex flex-col gap-5">
      <Link to="/follow/trade" className="w-fit text-[13px] text-ink-2 hover:text-ink">‹ 수출입</Link>
      <header className="flex flex-col gap-1">
        <span className="text-[13px] text-ink-3">{sub(hs, item)}</span>
        {view ? <h1 className="font-display text-page font-normal tracking-[-0.02em] max-md:text-[26px]">{view.name}</h1> : <Skeleton className="h-9 w-64" />}
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="font-display text-[32px] leading-tight tabular-nums">{val == null ? "-" : `${formatUsd(val)} · ${monthOf(view?.last?.period)}`}</span>
          <span className={cn("font-mono text-base tabular-nums", (view?.yoy ?? 0) > 0 ? "text-up-ink" : (view?.yoy ?? 0) < 0 ? "text-down-ink" : "text-ink-2")}>전년 대비 {formatPercent(view?.yoy ?? null)}</span>
        </div>
      </header>
      <section className="flex flex-col gap-4 border bg-card p-5 max-sm:p-3">
        {view ? <><BigChart data={view.points} height={360} barLabel="월별 수출액(5년)" fmt={formatUsd} /><StatGrid stats={view.stats} large /></>
          : <div role="status" aria-label="불러오는 중" className="flex flex-col gap-4"><Skeleton className="h-[384px] w-full" /><Skeleton className="h-[72px] w-full" /></div>}
      </section>
      <section className="flex flex-col gap-3 border bg-card p-5 max-sm:p-3">
        <div className="flex items-center gap-2">
          <h2 className="text-[15px] font-semibold">관련 종목</h2>
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => compute.mutate()} disabled={compute.isPending}>{compute.isPending ? "지목 중… (수 분)" : "다시 지목"}</Button>
        </div>
        {!view ? <Skeleton className="h-24 w-full" />
          : !view.bene.length ? <p className="text-sm text-ink-2">아직 지목한 종목이 없습니다.</p>
          : <ul className="divide-y">{view.bene.map((b, i) => <li key={i} className="flex items-start gap-2.5 py-2.5 text-[13px]">
            <Badge variant={b.rel === "수혜" ? "up" : b.rel === "피해" ? "down" : "neutral"} className="shrink-0">{b.rel ?? "-"}</Badge>
            <div className="min-w-0 flex-1">
              <span className="font-medium">{b.stock_code ? <Link to={`/analyze/${b.stock_code}/summary`} className="hover:underline">{b.name}</Link> : b.name}</span>
              {!b.in_universe && <span className="ml-1.5 text-xs text-ink-3">신규 후보</span>}
              {b.reason && <p className="mt-0.5 leading-snug text-ink-2">{b.reason}</p>}
            </div>
          </li>)}</ul>}
      </section>
    </div>
  </PageLayout>
}
