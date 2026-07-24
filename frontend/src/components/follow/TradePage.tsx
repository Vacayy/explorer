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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { cn } from "@/lib/utils"

/**
 * /follow/trade — 수출입(무역) 전용 페이지 (docs/specs/trade-follow.md, 2분할).
 * 좌: 팔로우 품목(구독) · 우: 수출입 추이 차트 + 관련 종목(LLM 논리 지목, D-036).
 */
interface FollowRow { hs_code: string; item_name: string; group_label: string | null; latest_period: string | null; latest_export: number | null; yoy_pct: number | null }
interface Stat { period: string; export_usd: number | null; import_usd: number | null; balance_usd: number | null }
interface Beneficiary { name: string; stock_code: string | null; rel: string | null; reason: string | null; rs: number | null; per: number | null; in_universe: boolean; universe_groups: string[] }
interface Detail { hs_code: string; item_name: string; series: Stat[]; beneficiaries: Beneficiary[] }

const usdB = (v: number | null) => v == null ? "-" : `$${(v / 1e9).toFixed(1)}B`
const GROUP_ORDER = ["반도체", "IT", "2차전지", "자동차", "에너지", "소재", "기계"]

export default function TradePage() {
  const [params, setParams] = useSearchParams()
  const selected = params.get("hs")
  const { data: follows = [], isLoading, isError, refetch } = useQuery(
    apiQuery<FollowRow[]>({ key: ["spine", "trade", "follow"], url: "/api/spine/trade/follow", staleTime: STALE.short }),
  )
  const qc = useQueryClient()
  const seed = useMutation({
    mutationFn: () => api.post("/api/spine/trade/seed").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "trade", "follow"] }),
  })
  const pick = (hs: string) => setParams({ hs }, { replace: true })

  if (isLoading) return <PageContainer><Skeleton className="h-96 w-full rounded-xl" /></PageContainer>
  if (isError) return <PageContainer><ErrorState onRetry={() => refetch()} /></PageContainer>

  const effective = selected ?? follows[0]?.hs_code ?? null

  return (
    <PageContainer>
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-bold">수출입</h2>
        <span className="text-xs text-muted-foreground">관세청 품목별 무역통계 · 팔로우 {follows.length}</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-4 items-start">
        <Card className="md:sticky md:top-16">
          <CardContent className="p-2 max-h-[70vh] overflow-y-auto">
            {follows.length === 0 ? (
              <div className="p-3 space-y-3">
                <p className="text-xs text-muted-foreground">팔로우가 비어 있습니다. 기본 품목 세트를 불러오세요.</p>
                <Button size="sm" onClick={() => seed.mutate()} disabled={seed.isPending}>
                  {seed.isPending ? "불러오는 중…" : "기본 품목 팔로우"}
                </Button>
              </div>
            ) : <ItemRail follows={follows} effective={effective} onPick={pick} />}
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

function ItemRail({ follows, effective, onPick }: { follows: FollowRow[]; effective: string | null; onPick: (hs: string) => void }) {
  const byGroup = useMemo(() => {
    const m = new Map<string, FollowRow[]>()
    for (const f of follows) { const g = f.group_label ?? "기타"; (m.get(g) ?? m.set(g, []).get(g))!.push(f) }
    return m
  }, [follows])
  const groups = [...GROUP_ORDER.filter((g) => byGroup.has(g)), ...[...byGroup.keys()].filter((g) => !GROUP_ORDER.includes(g))]
  return (
    <div className="space-y-1">
      {groups.map((g) => (
        <Collapsible key={g} defaultOpen>
          <CollapsibleTrigger className="flex w-full items-center gap-1 px-2 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground">
            <ChevronRight className="h-3 w-3 transition-transform data-[state=open]:rotate-90" /> {g}
          </CollapsibleTrigger>
          <CollapsibleContent className="pl-1">
            {byGroup.get(g)!.map((f) => (
              <button key={f.hs_code} onClick={() => onPick(f.hs_code)}
                className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left",
                  f.hs_code === effective ? "bg-accent text-accent-foreground" : "hover:bg-muted")}>
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate">{f.item_name}</div>
                  <div className="text-[10px] text-muted-foreground tabular-nums">{usdB(f.latest_export)}
                    {f.yoy_pct != null && <span className={f.yoy_pct >= 0 ? "text-up" : "text-down"}> {f.yoy_pct >= 0 ? "+" : ""}{f.yoy_pct}%</span>}</div>
                </div>
              </button>
            ))}
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
                    formatter={(v: number, name: string) => [name === "YoY" ? `${v}%` : `$${v}B`, name]} />
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
