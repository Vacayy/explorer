import { useSearchParams } from "react-router-dom"
import { useSpineFeed } from "@/hooks/useSpineFeed"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { SignalCard } from "@/components/shared/SignalCard"
import { formatRelativeTime } from "@/utils/format"

/**
 * analyze/:stockCode/mentions — 이 종목의 언급·신호 이력 (product-v2.md P1)
 * 디테일 = 상태의 전체: 이 종목에 대해 척추가 아는 모든 문서·신호.
 */
export default function MentionsPage({ stockCode }: { stockCode: string }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Number(searchParams.get("page") ?? "1")

  const feed = useSpineFeed({ stock: stockCode, page, size: 15 })
  const signals = useSpineSignals(undefined, 90)

  if (feed.isLoading || signals.isLoading) return <MentionsSkeleton />
  if (feed.isError || !feed.data) return <ErrorState onRetry={() => feed.refetch()} />

  const stockSignals = (signals.data?.items ?? []).filter((s) => s.stock_code === stockCode)
  const totalPages = Math.max(1, Math.ceil(feed.data.total / feed.data.size))

  return (
    <div className="space-y-5">
      {/* 신호 이력 (최근 90일) */}
      {stockSignals.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">신호 이력 (90일)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {stockSignals.map((s) => (
                <SignalCard key={s.id} signal={s} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 언급 문서 */}
      <Card>
        <CardHeader className="pb-2 flex-row items-baseline justify-between">
          <CardTitle className="text-sm">언급 문서 {feed.data.total}건</CardTitle>
          <FreshnessStamp asOf={feed.data.as_of} />
        </CardHeader>
        <CardContent>
          {feed.data.items.length === 0 ? (
            <EmptyState message="아직 이 종목을 언급한 수집 문서가 없습니다." />
          ) : (
            <ul className="divide-y">
              {feed.data.items.map((doc) => (
                <li key={doc.id} className="py-2.5 space-y-1">
                  <div className="flex items-center gap-2">
                    <SourceBadge sourceType={doc.source_type} />
                    <a href={doc.url || undefined} target="_blank" rel="noreferrer"
                       className="text-sm font-medium truncate hover:underline">
                      {doc.title || "(제목 없음)"}
                    </a>
                    <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
                      {formatRelativeTime(doc.published_at)}
                    </span>
                  </div>
                  {doc.summary && (
                    <p className="text-xs text-muted-foreground line-clamp-2">{doc.summary}</p>
                  )}
                </li>
              ))}
            </ul>
          )}

          {totalPages > 1 && (
            <div className="flex items-center justify-end gap-2 pt-3">
              <span className="text-xs text-muted-foreground tabular-nums">{page}/{totalPages}</span>
              <Button variant="outline" size="sm" disabled={page <= 1}
                onClick={() => setSearchParams({ page: String(page - 1) })}>이전</Button>
              <Button variant="outline" size="sm" disabled={page >= totalPages}
                onClick={() => setSearchParams({ page: String(page + 1) })}>다음</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function MentionsSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-32 w-full rounded-xl" />
      <div className="border rounded-xl p-4 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  )
}
