import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { ExternalLink } from "lucide-react"
import FilterChips from "@/components/shared/FilterChips"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { useSignals } from "@/hooks/useSignals"
import type { SignalItem } from "@/types"

const TYPE_OPTIONS = [
  { value: "all", label: "전체" },
  { value: "disclosure", label: "공시" },
  { value: "insider", label: "내부자거래" },
  { value: "contract", label: "대규모계약" },
]

const DAYS_OPTIONS = [
  { value: "1", label: "오늘" },
  { value: "7", label: "최근 7일" },
  { value: "30", label: "최근 30일" },
]

const TYPE_ICON: Record<string, string> = {
  disclosure: "📋",
  insider: "👤",
  contract: "📝",
}

function formatDateLabel(dateStr: string): string {
  const today = new Date()
  const todayStr = today.toISOString().slice(0, 10)
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const yesterdayStr = yesterday.toISOString().slice(0, 10)

  if (dateStr === todayStr) return `오늘 (${dateStr})`
  if (dateStr === yesterdayStr) return `어제 (${dateStr})`
  return dateStr
}

function groupByDate(items: SignalItem[]): [string, SignalItem[]][] {
  const map = new Map<string, SignalItem[]>()
  for (const item of items) {
    const d = item.date || "unknown"
    if (!map.has(d)) map.set(d, [])
    map.get(d)!.push(item)
  }
  return Array.from(map.entries())
}

export default function SignalFeedPage() {
  const navigate = useNavigate()
  const [type, setType] = useState("all")
  const [days, setDays] = useState("7")

  const { data, isLoading, isError, refetch } = useSignals({
    days: Number(days),
    type,
  })

  const items = data?.items ?? []
  const grouped = groupByDate(items)
  const isEmpty = !isLoading && !isError && items.length === 0
  // Detect watchlist-empty state: total=0 and no stock_codes queried
  // The backend returns empty when watchlist is empty
  const isWatchlistEmpty =
    !isLoading && !isError && data?.total === 0 && items.length === 0

  return (
    <div className="max-w-2xl mx-auto py-6 px-4 space-y-4">
      {/* Header + Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">시그널 피드</h1>
        <div className="flex items-center gap-2">
          <FilterChips options={TYPE_OPTIONS} value={type} onChange={setType} />
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger className="h-7 text-xs w-[110px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DAYS_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-14 rounded-lg bg-muted animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="text-center py-16 space-y-2 text-muted-foreground">
          <p>시그널을 불러올 수 없습니다</p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            재시도
          </Button>
        </div>
      )}

      {/* Watchlist empty */}
      {isWatchlistEmpty && (
        <div className="text-center py-16 space-y-2 text-muted-foreground">
          <p>워치리스트에 종목을 추가하면 시그널을 모아볼 수 있습니다</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate("/research/watchlist")}
          >
            워치리스트로 이동
          </Button>
        </div>
      )}

      {/* No signals (watchlist non-empty but no results) */}
      {!isLoading && !isError && !isWatchlistEmpty && isEmpty && (
        <div className="text-center py-16 text-muted-foreground">
          <p>
            최근{" "}
            {DAYS_OPTIONS.find((o) => o.value === days)?.label ?? `${days}일`}에
            시그널이 없습니다
          </p>
        </div>
      )}

      {/* Timeline */}
      {!isLoading && !isError && grouped.length > 0 && (
        <div className="space-y-6">
          {grouped.map(([date, dateItems]) => (
            <section key={date}>
              <h2 className="text-sm font-medium text-muted-foreground mb-2">
                {formatDateLabel(date)}
              </h2>
              <div className="border rounded-lg divide-y overflow-hidden">
                {dateItems.map((item, idx) => (
                  <SignalRow key={`${item.stock_code}-${idx}`} item={item} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

    </div>
  )
}

// ---------------------------------------------------------------------------

function SignalRow({ item }: { item: SignalItem }) {
  const navigate = useNavigate()
  const icon = TYPE_ICON[item.type] ?? "📋"

  return (
    <div className="flex items-start gap-3 px-4 py-3 hover:bg-muted/40 transition-colors">
      <span className="text-base leading-tight mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            className={cn(
              "text-sm font-semibold hover:underline text-left",
              "text-foreground"
            )}
            onClick={() => navigate(`/analyze/${item.stock_code}/summary`)}
          >
            {item.corp_name}
          </button>
          {item.in_watchlist && (
            <Badge variant="secondary" className="h-4 px-1 text-[10px]">
              ★
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
          {item.title}
        </p>
      </div>
      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 text-muted-foreground hover:text-foreground mt-0.5"
          aria-label="원문 보기"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      )}
    </div>
  )
}
