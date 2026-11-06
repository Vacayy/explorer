import { useMemo } from "react"
import { useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight } from "lucide-react"
import api from "@/api/client"
import { PageLayout } from "@/components/shared/PageLayout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import FilterChips from "@/components/shared/FilterChips"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { BoundedArea } from "@/components/shared/Bounded"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, RowsSkeleton, tone } from "@/components/home/blockState"
import { tradeIsLagging } from "@/components/home/TradeBlock"
import { SummaryStrip, SummaryStripSkeleton } from "@/components/industry/SummaryStrip"
import { MonitorSection, MonitorWall, WallPager, wallPageSize, type MonitorCardData } from "@/components/industry/MonitorWall"
import { TradeItemDialog } from "@/components/follow/TradeItem"
import { useDefaultWatchGroup } from "@/hooks/useGroups"
import { useTradeFollows, useTradeGrid, useTradeHighlights } from "@/hooks/useTrade"
import { useIsMobile } from "@/hooks/use-mobile"
import { TRADE_PERIOD_MONTHS, groupChips, monthLabel, pageOf, parseTradeGridSort, parseTradePeriod, rankTradeGrid, type TradeGridSort, type TradePeriod } from "@/lib/trade"
import { cn } from "@/lib/utils"
import { formatNumber, formatPercent, formatRatio, formatUsd } from "@/utils/format"
import type { TradeGridItem, TradeHighlights } from "@/types"

/**
 * 산업 › 수출입 (/follow/trade, 시안 Industry-Trade, ia-redesign §4.8a 11-06 모니터링형 · D-325 · docs/specs/trade-follow.md).
 * 요약 4칸 → 품목 모니터(팔로우 품목 전체 카드 벽, 산업 칩 · 정렬 · 기간 · 24개씩 쪽) →
 * 평소보다 크게 늘어난 품목(월 선택) | 산업별 수출. 카드·표 줄을 누르면 가운데 대화상자(URL hs), 거기서 상세 페이지 /follow/trade/:hs.
 * 벽은 일괄 API(/trade/grid) 하나로 그린다 — 칸마다 /trade/{hs}를 부르지 않는다.
 * URL: trade_group · trade_sort(value·surge·mine) · trade_period(2y·5y) · page · hs(대화상자) · month(급등 표 통계월).
 */
const SURGE_LIMIT = 100   // 급등 품목 수를 세려고 넉넉히 받는다(표는 상위만 보인다)
const SORTS: { value: TradeGridSort; label: string }[] = [{ value: "value", label: "수출액 순" }, { value: "surge", label: "급등 먼저" }, { value: "mine", label: "내 종목 관련" }]
const PERIODS: { value: TradePeriod; label: string }[] = [{ value: "2y", label: "2년" }, { value: "5y", label: "5년" }]

export default function TradePage() {
  const [params, setParams] = useSearchParams()
  const period = parseTradePeriod(params.get("trade_period"))
  const sort = parseTradeGridSort(params.get("trade_sort"))
  const group = params.get("trade_group") ?? "all"
  const hs = params.get("hs")
  const grid = useTradeGrid(TRADE_PERIOD_MONTHS[period])
  const hl = useTradeHighlights(SURGE_LIMIT, params.get("month"))
  const follows = useTradeFollows()   // 빈 상태(팔로우 0) 판정만 — 벽은 grid
  const qc = useQueryClient()
  const seed = useMutation({
    mutationFn: () => api.post("/api/spine/trade/seed").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "trade"] }),
  })
  /** 바꾸는 값 외의 쿼리는 그대로. 필터·정렬·기간이 바뀌면 첫 쪽으로 */
  const setMany = (kv: Record<string, string | null>) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) n.set(k, v); else n.delete(k) }
    return n
  }, { replace: true, preventScrollReset: true })

  if (follows.data && !follows.data.length) return <PageLayout mode="document"><Card><CardContent className="space-y-3 py-10 text-center">
    <EmptyState message="아직 팔로우하는 수출 품목이 없습니다." />
    <Button size="sm" onClick={() => seed.mutate()} disabled={seed.isPending}>{seed.isPending ? "불러오는 중…" : "기본 품목 팔로우"}</Button>
  </CardContent></Card></PageLayout>
  if (grid.isError && hl.isError) return <PageLayout mode="document"><ErrorState message="수출입 통계를 불러오지 못했습니다." onRetry={() => { void grid.refetch(); void hl.refetch() }} /></PageLayout>

  const item = grid.data?.items.find(i => i.hs_code === hs)
  return <PageLayout mode="document">
    <div className="flex flex-col">
      {hl.data && grid.data ? <TradeSummary d={hl.data} items={grid.data.items} />
        : hl.isError ? <BlockError message="수출 요약을 불러오지 못했습니다" error={hl.error} onRetry={() => void hl.refetch()} /> : <SummaryStripSkeleton />}
      <ItemMonitor q={grid} period={period} sort={sort} group={group} page={Number(params.get("page") ?? 1)}
        onChange={kv => setMany({ ...kv, page: null })} onPage={p => setMany({ page: p > 1 ? String(p) : null })}
        hrefOf={p => { const n = new URLSearchParams(params); if (p > 1) n.set("page", String(p)); else n.delete("page"); return `?${n}` }}
        onOpen={v => setMany({ hs: v })} />
      <div className="-mt-px grid lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:[&>*+*]:-ml-px max-lg:[&>*+*]:-mt-px">
        <SurgeBlock q={hl} onMonth={v => setMany({ month: v })} onPick={v => setMany({ hs: v })} />
        <GroupBlock q={hl} />
      </div>
    </div>
    <TradeItemDialog hs={hs} item={item} onClose={() => setMany({ hs: null })} />
  </PageLayout>
}

function TradeSummary({ d, items }: { d: TradeHighlights; items: TradeGridItem[] }) {
  const top = d.surge[0]
  const lag = tradeIsLagging(d.period)
  const surge = items.filter(i => i.flag === "surge").length
  return <SummaryStrip label="trade" cells={[
    { label: "수출 총액", value: formatUsd(d.total_usd), sub: <>{monthLabel(d.period)}{lag && <Badge variant="outline" className="ml-1.5 h-4 border-chart-warning/50 px-1 text-[10px] font-normal text-chart-warning">{+(d.period ?? "0000-00").slice(5, 7)}월 기준</Badge>}</> },
    { label: "팔로우 품목", value: formatNumber(items.length), sub: `세목 제외 · 급등 ${surge}` },
    { label: "평소보다 크게 늘어난 품목", value: formatNumber(d.surge.length), sub: "전년 대비 z ≥ 2" },
    { label: "기여 1위", value: <span className="font-sans text-xl max-md:text-lg">{top?.item_name ?? "-"}</span>, sub: top?.contribution != null ? `증가분의 ${formatRatio(top.contribution * 100)}` : undefined },
  ]} />
}

/** 내 종목(관심 묶음 국내 종목) — 품목의 관련 종목 코드(grid.stock_codes)와 겹치면 '내 종목 관련' */
function useMineHs(items: TradeGridItem[]): Set<string> {
  const watch = useDefaultWatchGroup()
  return useMemo(() => {
    const codes = new Set((watch.data?.members ?? []).map(m => m.stock_code))
    return new Set(items.filter(i => i.stock_codes.some(c => codes.has(c))).map(i => i.hs_code))
  }, [watch.data, items])
}

const toCard = (i: TradeGridItem, mine: boolean): MonitorCardData => ({
  key: i.hs_code, name: i.item_name, group: i.group_label ?? "미분류", value: i.latest_export == null ? "-" : formatUsd(i.latest_export),
  yoy: i.yoy_pct, surge: i.flag === "surge", badge: mine ? "내 종목" : i.flag === "new" ? "신규" : undefined,
  bars: i.series.map(p => p.export_usd), ma: i.series.map(p => p.ma12),
})

function ItemMonitor({ q, period, sort, group, page, onChange, onPage, hrefOf, onOpen }: {
  q: ReturnType<typeof useTradeGrid>; period: TradePeriod; sort: TradeGridSort; group: string; page: number
  onChange: (kv: Record<string, string | null>) => void; onPage: (p: number) => void; hrefOf: (p: number) => string; onOpen: (hs: string) => void
}) {
  const mobile = useIsMobile()
  const items = useMemo(() => q.data?.items ?? [], [q.data])
  const mine = useMineHs(items)
  const chips = useMemo(() => groupChips(items), [items])
  const g = chips.some(c => c.key === group) ? group : "all"
  const ranked = rankTradeGrid(items.filter(i => g === "all" || (i.group_label ?? "미분류") === g), sort, mine)
  const pg = pageOf(ranked, page, wallPageSize(mobile))
  const last = q.data?.period ? `${+q.data.period.slice(5, 7)}월` : "최신 달"
  return <MonitorSection label="trade.monitor">
    <BlockHead section title="품목 모니터" sub={<span className="max-sm:hidden">{`월별 수출액 ${period === "5y" ? "5년" : "2년"} · 막대 끝 = ${last} · 선 = 12개월 평균`}</span>}
      info="팔로우한 HS 품목(세목 제외)의 월별 수출액입니다. 분홍 막대는 이번 달 급등. 품목마다 규모가 달라 세로축이 다릅니다 — 비교는 전년 대비 숫자로 보세요. 카드를 누르면 상세가 가운데 창으로 열립니다." />
    <div className="flex items-center gap-2.5 max-lg:flex-col max-lg:items-stretch">
      {q.data ? <FilterChips options={chips.map(c => ({ value: c.key, label: c.label }))} value={g} onChange={v => onChange({ trade_group: v === "all" ? null : v })} className="min-w-0 flex-1 flex-nowrap overflow-x-auto [scrollbar-width:none]" />
        : <span className="h-7 flex-1" />}
      <div className="flex shrink-0 items-center gap-2 max-sm:justify-between">
        <SegmentTabs tabs={SORTS} value={sort} onChange={v => onChange({ trade_sort: v === "value" ? null : v })} />
        <SegmentTabs tabs={PERIODS} value={period} onChange={v => onChange({ trade_period: v === "2y" ? null : v })} />
      </div>
    </div>
    {sort === "mine" && q.data && !ranked.some(i => mine.has(i.hs_code)) && <p role="status" className="text-[13px] text-ink-2">내 종목과 이어진 품목이 아직 없습니다. 수출액 순으로 보입니다.</p>}
    {q.isError && !q.data ? <BlockError message="품목 목록을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : <MonitorWall cards={pg.rows.map(i => toCard(i, mine.has(i.hs_code)))} loading={q.isPending} onOpen={onOpen} empty="이 산업에는 팔로우한 품목이 없습니다." />}
    <WallPager from={pg.from} to={pg.to} total={ranked.length} page={pg.page} pages={pg.pages} hrefOf={hrefOf} onPage={onPage} />
  </MonitorSection>
}

function MonthNav({ d, onMonth }: { d: TradeHighlights; onMonth: (v: string | null) => void }) {
  const i = d.period ? d.periods.indexOf(d.period) : -1   // periods는 최신이 앞
  const go = (j: number) => onMonth(j <= 0 ? null : d.periods[j])
  return <span className="flex items-center gap-1">
    <Button variant="outline" size="icon-xs" aria-label="이전 달" disabled={i < 0 || i >= d.periods.length - 1} onClick={() => go(i + 1)}><ChevronLeft className="size-3.5" /></Button>
    <span className="min-w-20 text-center text-xs font-medium tabular-nums">{monthLabel(d.period)}</span>
    <Button variant="outline" size="icon-xs" aria-label="다음 달" disabled={i <= 0} onClick={() => go(i - 1)}><ChevronRight className="size-3.5" /></Button>
  </span>
}

type HlQuery = ReturnType<typeof useTradeHighlights>
/** 아래 두 칸 — 시안 높이 440 고정, 넘치면 안에서 스크롤 */
const LOWER = "-mt-px flex h-[440px] min-w-0 flex-col gap-3 border bg-card px-[18px] py-4 max-sm:h-[400px] max-sm:px-3"
const SURGE_COLS = "grid grid-cols-[minmax(0,1fr)_76px_76px_76px] gap-2 max-sm:grid-cols-[minmax(0,1fr)_64px_64px_56px]"

function SurgeBlock({ q, onMonth, onPick }: { q: HlQuery; onMonth: (v: string | null) => void; onPick: (hs: string) => void }) {
  const d = q.data
  return <section data-home-section="trade.surge" className={LOWER}>
    <BlockHead section title="평소보다 크게 늘어난 품목" sub={d ? `${monthLabel(d.period)} · ${d.surge.length}` : undefined}
      info="품목별 과거 변동 폭에 비해 전년 대비 증가가 이례적인(z ≥ 2, 1천만 달러 이상) 품목을 증가분 기여 순으로 고릅니다."
      actions={d ? <MonthNav d={d} onMonth={onMonth} /> : null} />
    <div className={cn(SURGE_COLS, "shrink-0 text-[11.5px] text-ink-3")}><span>품목</span><span className="text-right">수출액</span><span className="text-right">전년 대비</span><span className="text-right">증가분 기여</span></div>
    {!d ? (q.isError ? <BlockError message="품목 판정을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <RowsSkeleton rows={8} head={false} />)
      : !d.surge.length ? <p role="status" className="text-sm text-ink-2">{monthLabel(d.period)}에는 평소보다 크게 늘어난 품목이 없습니다.</p>
      : <BoundedArea fixed className="min-h-0 flex-1" viewportClassName="!h-full !max-h-none" aria-label="급등 품목">
        <ul>{d.surge.map(r => <li key={r.hs_code}>
          <Button variant="ghost" onClick={() => onPick(r.hs_code)} aria-label={`${r.item_name} 상세 열기`}
            className={cn(SURGE_COLS, "h-auto w-full items-center rounded-none border-b px-0 py-2 text-left text-[12.5px] font-normal whitespace-normal")}>
            <span className="min-w-0"><span className="block truncate font-medium">{r.item_name}</span>
              <span className="block truncate text-[11.5px] text-ink-3">{r.group_label ?? "미분류"} · HS {r.hs_code}</span></span>
            <span className="text-right font-mono tabular-nums">{r.value == null ? "-" : formatUsd(r.value)}</span>
            <span className={cn("text-right font-mono tabular-nums", tone(r.yoy))}>{formatPercent(r.yoy == null ? null : r.yoy * 100)}</span>
            <span className="text-right font-mono tabular-nums">{formatRatio(r.contribution == null ? null : r.contribution * 100)}</span>
          </Button>
        </li>)}</ul>
      </BoundedArea>}
  </section>
}

function GroupBlock({ q }: { q: HlQuery }) {
  const d = q.data
  const max = Math.max(1, ...(d?.groups ?? []).map(g => g.value))
  return <section data-home-section="trade.groups" className={LOWER}>
    <BlockHead section title="산업별 수출" sub={d ? monthLabel(d.period) : undefined} />
    {!d ? (q.isError ? <BlockError message="산업별 수출을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <RowsSkeleton rows={10} head={false} />)
      : <BoundedArea fixed className="min-h-0 flex-1" viewportClassName="!h-full !max-h-none" aria-label="산업별 수출">
        <ul>{d.groups.map(g => <li key={g.group_label} className="grid grid-cols-[minmax(0,132px)_1fr_52px_58px] items-center gap-2.5 py-[5px] text-[12.5px] max-sm:grid-cols-[minmax(0,96px)_1fr_52px_52px]">
          <span className="truncate">{g.group_label}</span>
          <span className="h-1.5 rounded-[3px] bg-chip" aria-hidden><span className="block h-1.5 rounded-[3px] bg-ink-2" style={{ width: `${Math.max(1.5, g.value / max * 100)}%` }} /></span>
          <span className="text-right font-mono tabular-nums">{formatUsd(g.value)}</span>
          <span className={cn("text-right font-mono tabular-nums", g.surge ? "text-up-ink" : "text-ink-3")}>{g.surge ? `급등 ${g.surge}` : "-"}</span>
        </li>)}</ul>
      </BoundedArea>}
  </section>
}
