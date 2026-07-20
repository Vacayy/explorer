import { Link } from "react-router-dom"
import { Sparkles } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/shared/ErrorState"

/** 내러티브 카드 목록 — 신호 티저(limit)와 월드모델>내러티브 랜딩이 공유. */
export interface NarrativeItem {
  topic: string
  title: string | null
  summary: string | null
  share_pct: number | null
  share_delta_pp: number | null
  is_new: boolean
  is_surging: boolean
  created_at: string | null
}

export function NarrativeList({ limit, empty = "hide" }: { limit?: number; empty?: "hide" | "state" }) {
  const { data } = useQuery(
    apiQuery<{ items: NarrativeItem[] }>({
      key: ["spine", "narrative", "list"],
      url: "/api/spine/narrative/list",
      staleTime: STALE.medium,
    }),
  )
  const items = data?.items ?? []
  if (items.length === 0) {
    return empty === "state"
      ? <EmptyState message="아직 생성된 내러티브가 없습니다 — 주목 주제가 쌓이면 나타납니다." />
      : null
  }
  const shown = limit ? items.slice(0, limit) : items

  return (
    <div className="space-y-2.5">
      {shown.map((n) => (
        <Link
          key={n.topic}
          to={`/narrative?topic=${encodeURIComponent(n.topic)}`}
          className="flex items-start gap-2 group"
        >
          <Sparkles className="h-4 w-4 text-hypothesis shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm leading-snug group-hover:underline">
                {n.title ?? n.topic}
              </span>
              <Badge variant="outline" className="text-[10px]">{n.topic}</Badge>
              {n.is_new ? (
                <span className="text-[10px] text-up">신규</span>
              ) : n.share_delta_pp ? (
                <span className="text-[10px] text-up tabular-nums">+{n.share_delta_pp}%p</span>
              ) : null}
            </div>
            {n.summary && (
              <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{n.summary}</p>
            )}
          </div>
        </Link>
      ))}
    </div>
  )
}
