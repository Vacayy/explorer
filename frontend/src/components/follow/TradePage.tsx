import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQueries, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, TrendingUp, Sparkles } from "lucide-react"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { PageLayout } from "@/components/shared/PageLayout"
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { HomeBlock } from "@/components/home/HomeSection"
import { BlockError, RowsSkeleton, tone } from "@/components/home/blockState"
import { tradeIsLagging } from "@/components/home/TradeBlock"
import { SummaryStrip, SummaryStripSkeleton } from "@/components/industry/SummaryStrip"
import { useDefaultWatchGroup } from "@/hooks/useGroups"
import { useTradeFollows, useTradeHighlights } from "@/hooks/useTrade"
import { useIsMobile } from "@/hooks/use-mobile"
import { monthLabel, movingAverage, parseTradeGridSort, rankTradeGrid, type TradeGridSort } from "@/lib/trade"
import { cn } from "@/lib/utils"
import { formatNumber, formatPercent, formatRatio, formatUsd } from "@/utils/format"
import type { TradeFollowRow, TradeHighlights, TradeStockItem } from "@/types"

/**
 * 산업 › 수출입 (/follow/trade, 시안 Industry-Trade, ia-redesign §4.8a · docs/specs/trade-follow.md).
 * 요약 줄(수출 총액 · 크게 늘어난/줄어든 품목 수 · 기여 1위) → 주요 품목 한눈에(수출액 상위 12, 36개월 막대 + 12개월 평균) →
 * 평소보다 크게 늘어난 품목(월 선택) | 산업별 수출. 품목을 누르면 옛 상세(수출입 추이 + 관련 종목, URL hs)를 시트로 연다.
 * URL: month(통계월, 없으면 최신) · trade_sort(value·surge·mine) · hs(상세).
 */
interface Stat { period: string; export_usd: number | null; import_usd: number | null; balance_usd: number | null }
interface Beneficiary { name: string; stock_code: string | null; rel: string | null; reason: string | null; rs: number | null; per: number | null; in_universe: boolean; universe_groups: string[] }
interface Detail { hs_code: string; item_name: string; series: Stat[]; beneficiaries: Beneficiary[] }

const detailQuery = (hs: string) => apiQuery<Detail>({ key: ["spine", "trade", hs], url: `/api/spine/trade/${hs}`, staleTime: STALE.medium })
const pct = (v: number | null | undefined) => formatPercent(v == null ? null : v * 100)
const SURGE_LIMIT = 100   // 급등 품목 수를 세려고 넉넉히 받는다(표는 상위만 보인다)

export default function TradePage() {
  const [params, setParams] = useSearchParams()
  const month = params.get("month")
  const follows = useTradeFollows()
  const hl = useTradeHighlights(SURGE_LIMIT, month)
  const qc = useQueryClient()
  const seed = useMutation({
    mutationFn: () => api.post("/api/spine/trade/seed").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "trade"] }),
  })
  const setParam = (k: string, v: string | null) => setParams((p) => {
    const n = new URLSearchParams(p)
    if (v) n.set(k, v); else n.delete(k)
    return n
  }, { replace: true, preventScrollReset: true })
  const hs = params.get("hs")

  if (follows.isPending && hl.isPending) return <PageLayout mode="document"><div className="flex flex-col"><SummaryStripSkeleton /><Skeleton className="h-[640px] w-full rounded-card" /></div></PageLayout>
  if (follows.isError && hl.isError) return <PageLayout mode="document"><ErrorState message="수출입 통계를 불러오지 못했습니다." onRetry={() => { void follows.refetch(); void hl.refetch() }} /></PageLayout>
  if (follows.data && !follows.data.length) return <PageLayout mode="document"><Card><CardContent className="space-y-3 py-10 text-center">
    <EmptyState message="아직 팔로우하는 수출 품목이 없습니다." />
    <Button size="sm" onClick={() => seed.mutate()} disabled={seed.isPending}>{seed.isPending ? "불러오는 중…" : "기본 품목 팔로우"}</Button>
  </CardContent></Card></PageLayout>

  return <PageLayout mode="document">
    <div className="flex flex-col">
      {hl.data ? <TradeSummary d={hl.data} /> : hl.isError ? <BlockError message="수출 요약을 불러오지 못했습니다" error={hl.error} onRetry={() => void hl.refetch()} /> : <SummaryStripSkeleton />}
      <TradeGrid follows={follows.data ?? []} loading={follows.isPending} error={follows.isError} onRetry={() => void follows.refetch()}
        sort={parseTradeGridSort(params.get("trade_sort"))} onSort={v => setParam("trade_sort", v === "value" ? null : v)} onPick={v => setParam("hs", v)} />
      <div className="surface-grid grid lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <SurgeTable q={hl} onMonth={v => setParam("month", v)} onPick={v => setParam("hs", v)} />
        <IndustryTable q={hl} />
      </div>
    </div>
    <DetailSheet hs={hs} name={follows.data?.find(f => f.hs_code === hs)?.item_name ?? null} onClose={() => setParam("hs", null)} />
  </PageLayout>
}

function TradeSummary({ d }: { d: TradeHighlights }) {
  const top = d.surge[0]
  const lag = tradeIsLagging(d.period)
  return <SummaryStrip label="trade" cells={[
    { label: "수출 총액", value: formatUsd(d.total_usd), sub: <>{monthLabel(d.period)}{lag && <Badge variant="outline" className="ml-1.5 h-4 border-chart-warning/50 px-1 text-[10px] font-normal text-chart-warning">{+(d.period ?? "0000-00").slice(5, 7)}월 기준</Badge>}</> },
    { label: "평소보다 크게 늘어난 품목", value: formatNumber(d.surge.length), sub: "전년 대비 z ≥ 2" },
    { label: "크게 줄어든 품목", value: formatNumber(d.plunge.length) },
    { label: "기여 1위", value: <span className="font-sans text-xl">{top?.item_name ?? "-"}</span>, sub: top?.contribution != null ? `증가분의 ${formatRatio(top.contribution * 100)}` : undefined },
  ]} />
}

/** 내 종목(관심 묶음 국내 종목)과 이어진 품목 — 종목 → 품목 역링크를 종목마다 읽는다. 정렬이 '내 종목 관련'일 때만 */
function useMineHs(enabled: boolean): Set<string> {
  const watch = useDefaultWatchGroup()
  const codes = enabled ? (watch.data?.members ?? []).map(m => m.stock_code).filter(c => /^\d{6}$/.test(c)) : []
  const qs = useQueries({ queries: codes.map(c => apiQuery<TradeStockItem[]>({ key: ["spine", "trade", "by-stock", c], url: `/api/spine/trade/by-stock/${c}`, staleTime: STALE.long })) })
  const key = qs.map(q => q.data?.map(i => i.hs_code).join(",") ?? "").join("|")
  // eslint-disable-next-line react-hooks/exhaustive-deps -- key가 결과 내용을 대표한다
  return useMemo(() => new Set(qs.flatMap(q => q.data?.map(i => i.hs_code) ?? [])), [key])
}

function TradeGrid({ follows, loading, error, onRetry, sort, onSort, onPick }: {
  follows: TradeFollowRow[]; loading: boolean; error: boolean; onRetry: () => void
  sort: TradeGridSort; onSort: (v: TradeGridSort) => void; onPick: (hs: string) => void
}) {
  const mine = useMineHs(sort === "mine")
  const items = rankTradeGrid(follows, sort, mine)
  return <HomeBlock label="trade.grid" title={<>주요 품목 한눈에 <span className="ml-1 text-xs font-normal text-muted-foreground">수출액 상위 {items.length || 12}</span></>}
    info="칸마다 최근 36개월 월별 수출 막대와 12개월 평균 선입니다. 품목마다 규모가 달라 세로축이 다릅니다 — 비교는 전년 대비 숫자로 보세요."
    actions={<ToggleGroup type="single" value={sort} onValueChange={v => { if (v) onSort(v as TradeGridSort) }} size="sm" aria-label="정렬" className="gap-1.5 bg-transparent p-0">
      <ToggleGroupItem value="value" className="h-7 rounded-full border border-line-2 px-3 text-xs shadow-none data-[state=on]:border-action data-[state=on]:bg-action data-[state=on]:text-action-ink data-[state=on]:shadow-none">수출액 순</ToggleGroupItem>
      <ToggleGroupItem value="surge" className="h-7 rounded-full border border-line-2 px-3 text-xs shadow-none data-[state=on]:border-action data-[state=on]:bg-action data-[state=on]:text-action-ink data-[state=on]:shadow-none">급등 먼저</ToggleGroupItem>
      <ToggleGroupItem value="mine" className="h-7 rounded-full border border-line-2 px-3 text-xs shadow-none data-[state=on]:border-action data-[state=on]:bg-action data-[state=on]:text-action-ink data-[state=on]:shadow-none">내 종목 관련</ToggleGroupItem>
    </ToggleGroup>} bodyClassName="p-0">
    {loading ? <div className="p-3"><RowsSkeleton rows={8} /></div>
      : error ? <div className="p-3"><BlockError message="품목 목록을 불러오지 못했습니다" onRetry={onRetry} /></div>
      : <>
        {sort === "mine" && !items.some(i => mine.has(i.hs_code)) && <p role="status" className="border-b px-3 py-2 text-sm text-muted-foreground">내 종목과 이어진 품목이 아직 없습니다. 수출액 순으로 보입니다.</p>}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 [&>*]:border-b sm:[&>*]:border-r">
          {items.map(f => <TradeCell key={f.hs_code} f={f} mine={mine.has(f.hs_code)} onPick={onPick} />)}
        </div>
      </>}
  </HomeBlock>
}

function TradeCell({ f, mine, onPick }: { f: TradeFollowRow; mine: boolean; onPick: (hs: string) => void }) {
  const q = useQuery(detailQuery(f.hs_code))
  const surge = f.flag === "surge" || f.flag === "new"
  const data = useMemo(() => {
    const s = (q.data?.series ?? []).slice(-47)
    const ma = movingAverage(s.map(p => p.export_usd))
    return s.map((p, i) => ({ period: p.period, v: p.export_usd, ma: ma[i] })).slice(-36)
  }, [q.data])
  const bene = (q.data?.beneficiaries ?? []).filter(b => b.rel === "수혜").slice(0, 2)
  return <Button variant="ghost" onClick={() => onPick(f.hs_code)} data-trade-cell aria-label={`${f.item_name} 상세`}
    className="flex h-auto w-full flex-col items-stretch justify-start gap-1.5 whitespace-normal rounded-none px-3.5 py-3 text-left font-normal">
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className="min-w-0 truncate text-[13px] font-semibold">{f.item_name}</span>
      {surge && <span className="inline-flex h-[18px] shrink-0 items-center rounded-[5px] bg-up-tint px-1.5 text-[11px] text-up-ink">급등</span>}
      {mine && <span className="inline-flex h-[18px] shrink-0 items-center rounded-[5px] bg-chip px-1.5 text-[11px] text-ink-2">내 종목</span>}
      <span className="ml-auto shrink-0 text-[11px] text-ink-3">{f.group_label ?? ""}</span>
    </span>
    <span className="flex items-baseline gap-2 font-mono tabular-nums">
      <span className="text-[17px]">{f.latest_export == null ? "-" : formatUsd(f.latest_export)}</span>
      <span className={cn("text-[12.5px]", tone(f.yoy_pct))}>전년 대비 {formatPercent(f.yoy_pct)}</span>
    </span>
    <span className="block aspect-[300/96]">
      {q.isPending ? <Skeleton className="h-full w-full" />
        : q.isError ? <span className="flex h-full items-center justify-center text-xs text-muted-foreground">추이를 불러오지 못했습니다</span>
        : <MiniBars data={data} last={surge ? "var(--up)" : "var(--ink)"} label={`${f.item_name} 최근 ${data.length}개월 수출액`} />}
    </span>
    <span className="block min-h-[15px] truncate text-[11.5px] text-ink-3">{bene.length > 0 && `수혜 ${bene.map(b => b.name).join(" · ")}`}</span>
  </Button>
}

/** 시안 Industry-Trade 칸 막대: 월별 수출(회색 55%, 마지막 달 = 급등이면 분홍·아니면 글자색) + 12개월 평균 선, 1월만 'YY.01' */
function MiniBars({ data, last, label }: { data: { period: string; v: number | null; ma: number | null }[]; last: string; label: string }) {
  const max = Math.max(0, ...data.map(p => Math.max(p.v ?? 0, p.ma ?? 0)))
  const step = 291 / Math.max(data.length, 1), w = step * 0.85
  const y = (v: number) => 80 - (max ? v / max : 0) * 70.5
  const ma = data.map((p, i) => p.ma == null ? null : `${(4.6 + i * step + w / 2).toFixed(1)},${y(p.ma).toFixed(1)}`).filter(Boolean).join(" ")
  return <svg viewBox="0 0 300 96" role="img" aria-label={label} className="block size-full">
    {data.map((p, i) => p.v == null ? null : <rect key={p.period} x={4.6 + i * step} y={y(p.v)} width={w} height={80 - y(p.v)} rx={1}
      fill={i === data.length - 1 ? last : "var(--ink-3)"} opacity={i === data.length - 1 ? 1 : 0.55}><title>{`${p.period} ${formatUsd(p.v)}`}</title></rect>)}
    {ma && <polyline points={ma} fill="none" stroke="var(--action)" strokeWidth={1.4} strokeLinejoin="round" />}
    {data.map((p, i) => p.period.endsWith("-01") && <text key={p.period} x={4.6 + i * step} y={93} fontSize={9.5} fill="var(--ink-3)">{`${p.period.slice(2, 4)}.01`}</text>)}
  </svg>
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

function SurgeTable({ q, onMonth, onPick }: { q: HlQuery; onMonth: (v: string | null) => void; onPick: (hs: string) => void }) {
  const d = q.data
  const mobile = useIsMobile()
  return <HomeBlock label="trade.surge" title="평소보다 크게 늘어난 품목"
    info="품목별 과거 변동 폭에 비해 전년 대비 증가가 이례적인(z ≥ 2, 1천만 달러 이상) 품목을 증가분 기여 순으로 고릅니다."
    actions={d ? <MonthNav d={d} onMonth={onMonth} /> : null} bodyClassName="p-0">
    {!d ? (q.isError ? <div className="p-3"><BlockError message="품목 판정을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /></div> : <div className="p-3"><RowsSkeleton rows={8} /></div>)
      : !d.surge.length ? <p role="status" className="p-3 text-sm text-muted-foreground">{monthLabel(d.period)}에는 평소보다 크게 늘어난 품목이 없습니다.</p>
      : <Table className="text-[13px]">
        <TableHeader><TableRow>
          <TableHead className="h-8 pl-3 text-[11px]">품목</TableHead>
          <TableHead className="h-8 text-right text-[11px]">수출액</TableHead>
          <TableHead className="h-8 text-right text-[11px]">전년 대비</TableHead>
          {!mobile && <TableHead className="h-8 text-right text-[11px]">전월 대비</TableHead>}
          {!mobile && <TableHead className="h-8 text-right text-[11px]">3개월 전년 대비</TableHead>}
          <TableHead className="h-8 pr-3 text-right text-[11px]">증가분 기여</TableHead>
        </TableRow></TableHeader>
        <TableBody>{d.surge.slice(0, 12).map(r => <TableRow key={r.hs_code} className="cursor-pointer" onClick={() => onPick(r.hs_code)}>
          <TableCell className="max-w-56 whitespace-normal py-2 pl-3">{r.item_name}
            <span className="block text-[11px] text-muted-foreground">{r.group_label ?? "미분류"} · HS {r.hs_code}</span></TableCell>
          <TableCell className="py-2 text-right font-mono tabular-nums">{r.value == null ? "-" : formatUsd(r.value)}</TableCell>
          <TableCell className={cn("py-2 text-right font-mono tabular-nums", tone(r.yoy))}>{pct(r.yoy)}</TableCell>
          {!mobile && <TableCell className={cn("py-2 text-right font-mono tabular-nums", tone(r.mom))}>{pct(r.mom)}</TableCell>}
          {!mobile && <TableCell className={cn("py-2 text-right font-mono tabular-nums", tone(r.yoy3m))}>{pct(r.yoy3m)}</TableCell>}
          <TableCell className="py-2 pr-3 text-right font-mono tabular-nums">{formatRatio(r.contribution == null ? null : r.contribution * 100)}</TableCell>
        </TableRow>)}</TableBody>
      </Table>}
  </HomeBlock>
}

function IndustryTable({ q }: { q: HlQuery }) {
  const d = q.data
  return <HomeBlock label="trade.groups" title={<>산업별 수출 {d && <span className="ml-1 text-xs font-normal text-muted-foreground">{d.groups.length}개 산업</span>}</>} bodyClassName="p-0">
    {!d ? (q.isError ? <div className="p-3"><BlockError message="산업별 수출을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /></div> : <div className="p-3"><RowsSkeleton rows={8} /></div>)
      : <Table className="text-[13px]">
        <TableHeader><TableRow>
          <TableHead className="h-8 pl-3 text-[11px]">산업</TableHead><TableHead className="h-8 text-right text-[11px]">수출액</TableHead>
          <TableHead className="h-8 text-right text-[11px]">비중</TableHead><TableHead className="h-8 text-right text-[11px] max-sm:hidden">품목</TableHead>
          <TableHead className="h-8 text-right text-[11px]">급등</TableHead><TableHead className="h-8 pr-3 text-right text-[11px]">급감</TableHead>
        </TableRow></TableHeader>
        <TableBody>{d.groups.map(g => <TableRow key={g.group_label}>
          <TableCell className="py-2 pl-3">{g.group_label}</TableCell>
          <TableCell className="py-2 text-right font-mono tabular-nums">{formatUsd(g.value)}</TableCell>
          <TableCell className="py-2 text-right font-mono tabular-nums">{formatRatio(d.total_usd ? g.value / d.total_usd * 100 : null)}</TableCell>
          <TableCell className="py-2 text-right font-mono tabular-nums max-sm:hidden">{g.count}</TableCell>
          <TableCell className={cn("py-2 text-right font-mono tabular-nums", g.surge ? "text-up-ink" : "text-muted-foreground")}>{g.surge || "-"}</TableCell>
          <TableCell className={cn("py-2 pr-3 text-right font-mono tabular-nums", g.plunge ? "text-down-ink" : "text-muted-foreground")}>{g.plunge || "-"}</TableCell>
        </TableRow>)}</TableBody>
      </Table>}
  </HomeBlock>
}

/** 품목 상세 — 옛 화면의 오른쪽(수출입 추이 + 관련 종목)을 시트로. 모바일은 아래에서 올라온다(§4.29) */
function DetailSheet({ hs, name, onClose }: { hs: string | null; name: string | null; onClose: () => void }) {
  const mobile = useIsMobile()
  return <Sheet open={!!hs} onOpenChange={v => { if (!v) onClose() }}>
    <SheetContent side={mobile ? "bottom" : "right"} className={cn("overflow-y-auto", mobile ? "max-h-[85dvh]" : "w-full sm:max-w-2xl")}>
      <SheetHeader className="pb-0"><SheetTitle>{name ?? "품목 상세"}</SheetTitle><SheetDescription className="sr-only">월별 수출입 추이와 관련 종목</SheetDescription></SheetHeader>
      <div className="px-4 pb-4">{hs && <TradeDetail key={hs} hs={hs} />}</div>
    </SheetContent>
  </Sheet>
}

function TradeDetail({ hs }: { hs: string }) {
  const qc = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<Detail>({ key: ["spine", "trade", hs], url: `/api/spine/trade/${hs}`, staleTime: STALE.medium }),
  )
  const compute = useMutation({
    mutationFn: () => api.post(`/api/spine/trade/${hs}/beneficiaries`, null, { timeout: 300_000 }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "trade", hs] }),
  })

  if (isLoading) return <Card><CardContent className="py-3 space-y-3"><Skeleton className="h-5 w-40" /><Skeleton className="h-56 w-full" /></CardContent></Card>
  if (isError || !data) return <Card><CardContent className="py-10"><ErrorState onRetry={() => refetch()} /></CardContent></Card>

  // 금액=bar($B), 수출 YoY%=line(별도 축). YoY = 전년 동월 대비.
  const expByPeriod = new Map(data.series.map((s) => [s.period, s.export_usd]))
  const rows = data.series.map((s) => {
    const [y, m] = s.period.split("-")
    const prev = expByPeriod.get(`${Number(y) - 1}-${m}`)
    const yoy = prev && s.export_usd ? (s.export_usd / prev - 1) * 100 : null
    return {
      period: s.period,
      수출: s.export_usd != null ? +(s.export_usd / 1e9).toFixed(2) : null,
      수입: s.import_usd != null ? +(s.import_usd / 1e9).toFixed(2) : null,
      YoY: yoy != null ? Math.round(yoy * 10) / 10 : null,
    }
  })

  return (
    <Card>
      <CardContent className="py-3 space-y-4">
        <div className="flex items-center gap-2">
          <span className="font-bold text-lg">{data.item_name}</span>
          <Badge variant="secondary" className="text-[11px]">HS {data.hs_code}</Badge>
        </div>

        <section className="border p-3">
          <h4 className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <TrendingUp className="h-4 w-4" /> 월별 수출입 (bar, $B) · 수출 YoY (line, %)
          </h4>
          {rows.length === 0 ? <EmptyState message="통계 없음 — 관리자에서 '수출입 수집' 실행" />
            : (
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={rows} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="period" tick={{ fontSize: 10 }} tickFormatter={(p: string) => p.slice(2)} minTickGap={24} />
                  <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${v}B`} width={44} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} width={40} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }}
                    formatter={(v, name) => [name === "YoY" ? `${v as number}%` : `$${v as number}B`, name as string]} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="left" dataKey="수출" fill="var(--color-chart-blue)" opacity={0.85} />
                  <Bar yAxisId="left" dataKey="수입" fill="var(--color-chart-orange)" opacity={0.85} />
                  <Line yAxisId="right" type="monotone" dataKey="YoY" stroke="var(--color-chart-purple)" strokeWidth={2} dot={false} connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            )}
        </section>

        <section>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-hypothesis" /> 관련 종목 (파급 논리)</h4>
            <Button size="sm" variant="outline" onClick={() => compute.mutate()} disabled={compute.isPending}>
              {compute.isPending ? "지목 중… (수 분)" : "다시 지목"}
            </Button>
          </div>
          {data.beneficiaries.length === 0 ? (
            compute.isPending ? <Skeleton className="h-20 w-full" />
              : <p className="text-xs text-muted-foreground py-3">아직 지목 전 — "다시 지목"으로 LLM이 이 품목 추이의 수혜/피해 종목을 인과 논리로 뽑습니다.</p>
          ) : (
            <ul className="space-y-1.5">
              {data.beneficiaries.map((b, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <Badge variant="outline" className={cn("text-[9px] shrink-0", b.rel === "수혜" ? "text-up-ink border-up/40" : "text-down-ink border-down/40")}>{b.rel}</Badge>
                  <div className="min-w-0 flex-1">
                    <span className="font-medium">
                      {b.stock_code ? <Link to={`/analyze/${b.stock_code}/summary`} className="text-primary hover:underline">{b.name}</Link> : b.name}
                    </span>
                    {b.rs != null && <span className="ml-1.5 text-[10px] text-muted-foreground tabular-nums">RS {b.rs}</span>}
                    {b.in_universe
                      ? <Badge variant="secondary" className="ml-1.5 text-[9px]">★유니버스</Badge>
                      : <Badge variant="outline" className="ml-1.5 text-[9px] text-muted-foreground">신규후보</Badge>}
                    <p className="text-muted-foreground leading-snug mt-0.5">{b.reason}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </CardContent>
    </Card>
  )
}
