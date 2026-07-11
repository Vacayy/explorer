import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { SignalCard } from "@/components/shared/SignalCard"
import { cn } from "@/lib/utils"

const TYPE_FILTERS = [
  { key: "", label: "전체" },
  { key: "mention_surge", label: "언급 급증" },
  { key: "high_52w", label: "52주 신고가" },
  // 확장 예정: export_change(수출 변화) — 무역 커넥터 후
] as const

const DAYS_FILTERS = [7, 30] as const

/**
 * /explore — 탐색 (product-v2.md v2.1)
 * P0: 신호 카드 피드. 스캔(신고가)·섹터 렌즈는 P1.
 * URL 쿼리(type/days)가 필터 상태의 단일 소스.
 */
export default function ExplorePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const type = searchParams.get("type") ?? ""
  const days = Number(searchParams.get("days") ?? "7")
  const { data, isLoading, isError, refetch } = useSpineSignals(type || undefined, days)

  const setParam = (key: string, value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    })
  }

  if (isLoading) return <ExploreSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-bold">신호</h2>
        <FreshnessStamp asOf={data.as_of} />
      </div>

      {/* 필터: 타입 + 기간 */}
      <div className="flex items-center gap-2 flex-wrap">
        {TYPE_FILTERS.map((f) => (
          <Badge
            key={f.key}
            variant={type === f.key ? "default" : "outline"}
            className="cursor-pointer select-none text-xs"
            onClick={() => setParam("type", f.key)}
          >
            {f.label}
          </Badge>
        ))}
        <span className="mx-1 text-muted-foreground text-xs">·</span>
        {DAYS_FILTERS.map((d) => (
          <button
            key={d}
            className={cn(
              "text-xs px-2 py-0.5 rounded-md",
              days === d ? "bg-muted font-semibold" : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setParam("days", String(d))}
          >
            {d}일
          </button>
        ))}
      </div>

      <MomentumSection />

      <BacktestSection />

      {/* 신호 카드 그리드 */}
      {data.items.length === 0 ? (
        <EmptyState message={`최근 ${days}일 신호가 없습니다. 수집이 쌓이면 여기에 나타납니다.`} />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {data.items.map((s) => (
            <SignalCard
              key={s.id}
              signal={s}
              onKeywordClick={(k) => navigate(`/feed?topic=${encodeURIComponent(k)}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ExploreSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-6 w-24" />
      <Skeleton className="h-5 w-64" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="border rounded-xl p-4 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-5 w-28" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        ))}
      </div>
    </div>
  )
}


/* ---------- 언급 모멘텀 랭킹 — 이번 주 부상 종목 (새 탭 없이 /explore 착륙) ---------- */

interface MomentumRow {
  rank: number
  entity_id: number
  name: string
  stock_code: string | null
  count_7d: number
  prior_7d: number
  score: number
  daily: number[]
}

function Spark({ data }: { data: number[] }) {
  const max = Math.max(...data, 1)
  const w = 3, gap = 1
  return (
    <svg width={data.length * (w + gap)} height={14} className="shrink-0 opacity-80">
      {data.map((v, i) => {
        const h = Math.max(1, Math.round((v / max) * 13))
        return <rect key={i} x={i * (w + gap)} y={14 - h} width={w} height={h} rx={0.5}
          className={i >= data.length - 7 ? "fill-primary" : "fill-muted-foreground/40"} />
      })}
    </svg>
  )
}

function MomentumSection() {
  const { data } = useQuery({
    queryKey: ["spine", "momentum"],
    queryFn: async () => (await api.get("/api/spine/signals/momentum")).data as { items: MomentumRow[] },
    staleTime: 5 * 60_000,
  })
  const items = data?.items ?? []
  if (items.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">언급 모멘텀 — 이번 주 부상 종목</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1">
          {items.map((m) => (
            <div key={m.entity_id} className="flex items-center gap-2 py-1 text-sm">
              <span className="w-5 text-right text-xs text-muted-foreground tabular-nums">{m.rank}</span>
              {m.stock_code ? (
                <Link to={`/analyze/${m.stock_code}/mentions`} className="font-medium text-primary hover:underline truncate">
                  {m.name}
                </Link>
              ) : <span className="font-medium truncate">{m.name}</span>}
              <span className="ml-auto shrink-0 flex items-center gap-2 text-xs tabular-nums">
                <Spark data={m.daily} />
                7일 <b>{m.count_7d}</b>회
                <span className="text-muted-foreground">(직전 {m.prior_7d})</span>
                {m.score >= 2 && <span className="text-up">×{m.score}</span>}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}


/* ---------- 신호 성적표 — 언급 급증 후 5거래일 수익률 (자기 검증) ---------- */

function BacktestSection() {
  const { data } = useQuery({
    queryKey: ["spine", "backtest"],
    queryFn: async () => (await api.get("/api/spine/signals/backtest")).data as {
      items: { date: string; name: string; stock_code: string | null; ret_5d: number | null }[]
      avg_ret: number | null
      hit_rate: number | null
      n: number
    },
    staleTime: 30 * 60_000,
  })
  if (!data || data.n === 0) return null
  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-baseline gap-3">
        <CardTitle className="text-sm">신호 성적표 — 언급 급증 후 5거래일</CardTitle>
        <span className="text-xs tabular-nums">
          평균 <b className={data.avg_ret! > 0 ? "text-up" : "text-down"}>{data.avg_ret}%</b>
          <span className="text-muted-foreground"> · 적중 {data.hit_rate}% · {data.n}건</span>
        </span>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
          {data.items.filter((i) => i.ret_5d != null).slice(0, 12).map((i, idx) => (
            <span key={idx}>
              <span className="text-muted-foreground">{i.date.slice(5)}</span>{" "}
              {i.name}{" "}
              <b className={i.ret_5d! > 0 ? "text-up" : "text-down"}>
                {i.ret_5d! > 0 ? "+" : ""}{i.ret_5d}%
              </b>
            </span>
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground mt-2">
          과거 신호의 사후 수익률 — 신호의 유효성 자체를 검증하기 위한 것 (투자 추천 아님)
        </p>
      </CardContent>
    </Card>
  )
}
