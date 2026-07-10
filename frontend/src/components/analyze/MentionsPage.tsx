import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import ReactMarkdown from "react-markdown"
import { ChevronDown, ChevronUp, Lightbulb } from "lucide-react"
import api from "@/api/client"
import { Badge } from "@/components/ui/badge"
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
      <DigestSection stockCode={stockCode} />

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
                    <Link to={`/doc/${doc.id}`}
                       className="text-sm font-medium truncate hover:underline">
                      {doc.title || "(제목 없음)"}
                    </Link>
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


/* ---------- 언급 다이제스트 (1D / 롤링 7D) ---------- */

interface DigestItem {
  period: string
  period_start: string
  digest: string | null
  insights: string | null
  doc_count: number | null
  model: string | null
}

function DigestSection({ stockCode }: { stockCode: string }) {
  const [period, setPeriod] = useState<"1d" | "7d">("1d")
  const [showArchive, setShowArchive] = useState(false)
  const { data } = useQuery({
    queryKey: ["spine", "digests", stockCode, period],
    queryFn: async () =>
      (await api.get("/api/spine/digests", { params: { stock: stockCode, period } })).data as {
        items: DigestItem[]
      },
    staleTime: 5 * 60_000,
  })

  const items = data?.items ?? []
  const latest = items[0]
  const archive = items.slice(1)

  return (
    <Card className="border-l-2 border-l-hypothesis">
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <CardTitle className="text-sm">언급 요약</CardTitle>
        <div className="flex rounded-md border overflow-hidden">
          {(["1d", "7d"] as const).map((p) => (
            <button key={p}
              className={p === period
                ? "px-2 py-0.5 text-[11px] bg-primary text-primary-foreground font-medium"
                : "px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"}
              onClick={() => setPeriod(p)}>
              {p === "1d" ? "1D" : "7D 롤링"}
            </button>
          ))}
        </div>
        {latest && (
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            {latest.period_start} 기준 · 문서 {latest.doc_count ?? "-"}건 ·
            <Badge variant="outline" className="ml-1 text-[9px] font-normal text-hypothesis border-hypothesis/40">
              AI 요약 {latest.model}
            </Badge>
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {!latest ? (
          <p className="text-xs text-muted-foreground py-2">
            아직 요약이 없습니다. 언급이 수집되면 30분 주기로 생성됩니다.
          </p>
        ) : (
          <>
            {/* 새로운 시각 — 이전 요약 대비 새 이슈/시각 전환 */}
            {latest.insights && (
              <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
                <Lightbulb className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
                <p className="text-xs"><span className="font-semibold text-hypothesis">새로운 시각</span> {latest.insights}</p>
              </div>
            )}
            <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_h3]:text-[13px] [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:my-1.5">
              <ReactMarkdown>{latest.digest ?? ""}</ReactMarkdown>
            </div>

            {archive.length > 0 && (
              <div className="border-t pt-2">
                <button onClick={() => setShowArchive(!showArchive)}
                  className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
                  {showArchive ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  지난 요약 {archive.length}건
                </button>
                {showArchive && (
                  <div className="space-y-3 pt-2">
                    {archive.map((d) => (
                      <div key={d.period_start} className="rounded-md border px-3 py-2">
                        <div className="text-[11px] text-muted-foreground tabular-nums mb-1">
                          {d.period_start} · 문서 {d.doc_count ?? "-"}건
                        </div>
                        {d.insights && (
                          <p className="text-[11px] text-hypothesis mb-1">💡 {d.insights}</p>
                        )}
                        <div className="prose prose-sm dark:prose-invert max-w-none text-xs [&_p]:my-1">
                          <ReactMarkdown>{d.digest ?? ""}</ReactMarkdown>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
