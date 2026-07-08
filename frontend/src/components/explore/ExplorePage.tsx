import { useNavigate, useSearchParams } from "react-router-dom"
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
