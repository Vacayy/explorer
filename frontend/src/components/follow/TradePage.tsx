import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { TrendingUp, ChevronRight, Sparkles } from "lucide-react"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { PageContainer } from "@/components/shared/PageContainer"
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { TradeFlagBadge } from "@/components/follow/tradeFormat"
import { useTradeFollows } from "@/hooks/useTrade"
import { cn } from "@/lib/utils"
import { formatPercent, formatUsd } from "@/utils/format"
import type { TradeFollowRow } from "@/types"

/**
 * /follow/trade — 수출입(무역) 전용 페이지 (docs/specs/trade-follow.md, 2분할).
 * 좌: 팔로우 품목 — 서버 판정(급등·급감 배지, 사유 툴팁), 기본 '이번 달 기여도 순' · 우: 수출입 추이 차트 + 관련 종목(LLM 논리 지목, D-036).
 */
interface Stat { period: string; export_usd: number | null; import_usd: number | null; balance_usd: number | null }
interface Beneficiary { name: string; stock_code: string | null; rel: string | null; reason: string | null; rs: number | null; per: number | null; in_universe: boolean; universe_groups: string[] }
interface Detail { hs_code: string; item_name: string; series: Stat[]; beneficiaries: Beneficiary[] }

const usdB = (v: number | null) => v == null ? "-" : formatUsd(v)
type RailSort = "contribution" | "group"

export default function TradePage() {
  const [params, setParams] = useSearchParams()
  const selected = params.get("hs")
  const sort: RailSort = params.get("trade_sort") === "group" ? "group" : "contribution"
  const { data: follows = [], isLoading, isError, refetch } = useTradeFollows()
  const qc = useQueryClient()
  const seed = useMutation({
    mutationFn: () => api.post("/api/spine/trade/seed").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "trade", "follow"] }),
  })
  const setParam = (k: string, v: string | null) => setParams((p) => {
    const n = new URLSearchParams(p)
    if (v) n.set(k, v); else n.delete(k)
    return n
  }, { replace: true })

  const ranked = useMemo(() => rankByContribution(follows), [follows])
  if (isLoading) return <PageContainer><Skeleton className="h-96 w-full rounded-xl" /></PageContainer>
  if (isError) return <PageContainer><ErrorState onRetry={() => refetch()} /></PageContainer>

  const effective = selected ?? ranked[0]?.hs_code ?? null
  const period = follows.find((f) => f.latest_period)?.latest_period
  const surge = follows.filter((f) => f.flag === "surge").length
  const plunge = follows.filter((f) => f.flag === "plunge").length

  return (
    <PageContainer>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-xl font-bold">수출입</h2>
        <span className="text-xs text-muted-foreground tabular-nums">
          관세청 품목별 무역통계{period && ` · ${period} 기준`} · 팔로우 {follows.length}
          {follows.length > 0 && <> · <span className="text-up">급등 {surge}</span> · <span className="text-down">급감 {plunge}</span></>}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4 items-start">
        <Card className="md:sticky md:top-16 py-0">
          <CardContent className="p-2 space-y-2">
            {follows.length === 0 ? (
              <div className="p-3 space-y-3">
                <p className="text-xs text-muted-foreground">팔로우가 비어 있습니다. 기본 품목 세트를 불러오세요.</p>
                <Button size="sm" onClick={() => seed.mutate()} disabled={seed.isPending}>
                  {seed.isPending ? "불러오는 중…" : "기본 품목 팔로우"}
                </Button>
              </div>
            ) : <>
              <ToggleGroup type="single" size="sm" variant="outline" value={sort} className="w-full"
                onValueChange={(v) => v && setParam("trade_sort", v === "contribution" ? null : v)}>
                <ToggleGroupItem value="contribution" className="flex-1 text-xs">이번 달 기여도</ToggleGroupItem>
                <ToggleGroupItem value="group" className="flex-1 text-xs">분류별</ToggleGroupItem>
              </ToggleGroup>
              <div className="max-h-[45vh] md:max-h-[70vh] overflow-y-auto">
                {sort === "contribution"
                  ? <div className="space-y-0.5">{ranked.map((f) => <RailItem key={f.hs_code} f={f} follows={follows} active={f.hs_code === effective} onPick={(hs) => setParam("hs", hs)} />)}</div>
                  : <GroupRail follows={follows} effective={effective} onPick={(hs) => setParam("hs", hs)} />}
              </div>
            </>}
          </CardContent>
        </Card>

        <div className="min-w-0">
          {effective
            ? <TradeDetail key={effective} hs={effective} />
            : <Card><CardContent className="py-16"><EmptyState message="품목을 선택하세요." /></CardContent></Card>}
        </div>
      </div>
    </PageContainer>
  )
}

/** 이번 달 기여도 내림차순 — 판정 있는 품목이 같은 기여도면 앞, 기여도 없음은 뒤 */
function rankByContribution(follows: TradeFollowRow[]): TradeFollowRow[] {
  const flagged = (f: TradeFollowRow) => (f.flag && f.flag !== "none" ? 1 : 0)
  return [...follows].sort((a, b) => (b.contribution ?? -1) - (a.contribution ?? -1) || flagged(b) - flagged(a))
}

function RailItem({ f, follows, active, onPick }: { f: TradeFollowRow; follows: TradeFollowRow[]; active: boolean; onPick: (hs: string) => void }) {
  const parent = f.nested_in ? follows.find((x) => x.hs_code === f.nested_in)?.item_name ?? f.nested_in : null
  return (
    <Button variant="ghost" onClick={() => onPick(f.hs_code)}
      className={cn("h-auto w-full justify-start gap-2 px-2 py-1.5 text-left font-normal", active && "bg-accent text-accent-foreground")}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm">{f.item_name}</span>
          <TradeFlagBadge flag={f.flag} reason={f.reason} contribution={f.contribution} nestedIn={parent} />
        </div>
        <div className="text-[10px] text-muted-foreground tabular-nums">
          {usdB(f.latest_export)}
          {f.yoy_pct != null && <span className={f.yoy_pct >= 0 ? "text-up" : "text-down"}> {formatPercent(f.yoy_pct)}</span>}
          {parent && <span> · {parent}의 세목</span>}
        </div>
      </div>
    </Button>
  )
}

/** 분류별 보기 — 분류는 최상위 품목 금액 합이 큰 순(하위 세목은 합에서 제외) */
function GroupRail({ follows, effective, onPick }: { follows: TradeFollowRow[]; effective: string | null; onPick: (hs: string) => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, { rows: TradeFollowRow[]; value: number }>()
    for (const f of follows) {
      const g = f.group_label ?? "기타"
      const e = m.get(g) ?? m.set(g, { rows: [], value: 0 }).get(g)!
      e.rows.push(f)
      if (!f.nested_in) e.value += f.latest_export ?? 0
    }
    return [...m.entries()].sort((a, b) => b[1].value - a[1].value)
  }, [follows])
  return (
    <div className="space-y-1">
      {groups.map(([g, e]) => (
        <Collapsible key={g} defaultOpen>
          <CollapsibleTrigger className="flex w-full items-center gap-1 px-2 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground">
            <ChevronRight className="h-3 w-3 transition-transform data-[state=open]:rotate-90" /> {g}
            <span className="ml-auto tabular-nums">{usdB(e.value)}</span>
          </CollapsibleTrigger>
          <CollapsibleContent className="pl-1">
            {e.rows.map((f) => <RailItem key={f.hs_code} f={f} follows={follows} active={f.hs_code === effective} onPick={onPick} />)}
          </CollapsibleContent>
        </Collapsible>
      ))}
    </div>
  )
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

  if (isLoading) return <Card><CardContent className="py-6 space-y-3"><Skeleton className="h-5 w-40" /><Skeleton className="h-56 w-full" /></CardContent></Card>
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
      <CardContent className="py-5 space-y-4">
        <div className="flex items-center gap-2">
          <span className="font-bold text-lg">{data.item_name}</span>
          <Badge variant="secondary" className="text-[11px]">HS {data.hs_code}</Badge>
        </div>

        <section className="rounded-lg border p-3">
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
                  <Badge variant="outline" className={cn("text-[9px] shrink-0", b.rel === "수혜" ? "text-up border-up/40" : "text-down border-down/40")}>{b.rel}</Badge>
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
