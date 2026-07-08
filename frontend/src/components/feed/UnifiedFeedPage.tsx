import { Link, useSearchParams } from "react-router-dom"
import { Search, X } from "lucide-react"
import { useSpineFeed } from "@/hooks/useSpineFeed"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { EntityChip } from "@/components/shared/EntityChip"
import { formatRelativeTime } from "@/utils/format"
import type { EntityTag, FeedDocument } from "@/types"

/**
 * /feed — 통합 피드 (product-v2.md v2.1)
 * URL 쿼리 파라미터(source/stock/industry/topic/page)가 필터 상태의 단일 소스.
 * 엔티티 칩 클릭 = 해당 필터 적용.
 */
export default function UnifiedFeedPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = {
    q: searchParams.get("q") ?? undefined,
    source: searchParams.get("source") ?? undefined,
    stock: searchParams.get("stock") ?? undefined,
    industry: searchParams.get("industry") ?? undefined,
    topic: searchParams.get("topic") ?? undefined,
    page: Number(searchParams.get("page") ?? "1"),
    size: 20,
  }
  const { data, isLoading, isError, refetch, isPlaceholderData } = useSpineFeed(filters)

  const setFilter = (key: string, value: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      next.delete("page") // 필터 변경 시 1페이지로
      return next
    })
  }

  const onChipFilter = (tag: EntityTag) => {
    if (tag.link_type === "stock" && tag.aliases) setFilter("stock", tag.aliases)
    else if (tag.link_type === "industry") setFilter("industry", tag.name)
    else if (tag.link_type === "topic") setFilter("topic", tag.name)
  }

  if (isLoading) return <FeedSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const totalPages = Math.max(1, Math.ceil(data.total / data.size))
  const activeFilters = (["stock", "industry", "topic"] as const).filter((k) => filters[k])

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-bold">피드</h2>
        <FreshnessStamp asOf={data.as_of} />
      </div>

      {/* 하이브리드 검색 (BM25+벡터) — Enter로 실행, URL ?q= 동기화 */}
      <form
        className="relative max-w-md"
        onSubmit={(e) => {
          e.preventDefault()
          const v = new FormData(e.currentTarget).get("q")?.toString().trim() ?? ""
          setFilter("q", v || null)
        }}
      >
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input name="q" defaultValue={filters.q ?? ""} placeholder="문서 검색 (의미 기반)…" className="pl-8 h-8 text-sm" />
        {filters.q && (
          <button type="button" onClick={() => setFilter("q", null)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </form>

      {/* 활성 필터 칩 (제거 가능) */}
      {activeFilters.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-muted-foreground">필터:</span>
          {activeFilters.map((k) => (
            <Badge key={k} variant="secondary" className="text-xs gap-1 pr-1">
              {k === "stock" ? `종목 ${filters[k]}` : filters[k]}
              <button onClick={() => setFilter(k, null)} aria-label="필터 제거">
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setSearchParams(filters.source ? { source: filters.source } : {})}
          >
            모두 지우기
          </Button>
        </div>
      )}

      {/* 문서 리스트 */}
      {data.items.length === 0 ? (
        <EmptyState message="조건에 맞는 문서가 없습니다. 필터를 지우거나 소스를 추가해보세요." />
      ) : (
        <div className={`space-y-3 ${isPlaceholderData ? "opacity-60" : ""}`}>
          {data.items.map((doc) => (
            <DocumentCard key={doc.id} doc={doc} onChipFilter={onChipFilter} />
          ))}
        </div>
      )}

      {/* 페이지네이션 */}
      <div className="flex items-center justify-between pt-2">
        <span className="text-xs text-muted-foreground tabular-nums">
          총 {data.total}건 · {filters.page}/{totalPages} 페이지
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline" size="sm"
            disabled={filters.page <= 1}
            onClick={() => setSearchParams((p) => { const n = new URLSearchParams(p); n.set("page", String(filters.page - 1)); return n })}
          >
            이전
          </Button>
          <Button
            variant="outline" size="sm"
            disabled={filters.page >= totalPages}
            onClick={() => setSearchParams((p) => { const n = new URLSearchParams(p); n.set("page", String(filters.page + 1)); return n })}
          >
            다음
          </Button>
        </div>
      </div>
    </div>
  )
}

function DocumentCard({ doc, onChipFilter }: {
  doc: FeedDocument
  onChipFilter: (tag: EntityTag) => void
}) {
  const stockTags = doc.entities.filter((e) => e.link_type === "stock")
  const otherTags = doc.entities.filter((e) => e.link_type !== "stock")

  return (
    <Card>
      <CardContent className="py-3 space-y-1.5">
        <div className="flex items-center gap-2">
          <SourceBadge sourceType={doc.source_type} />
          <a
            href={doc.url || undefined}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-sm truncate hover:underline"
          >
            {doc.title || "(제목 없음)"}
          </a>
          <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
            {formatRelativeTime(doc.published_at)}
          </span>
        </div>

        {doc.summary && (
          <p className="text-xs text-muted-foreground line-clamp-2">{doc.summary}</p>
        )}

        {(stockTags.length > 0 || otherTags.length > 0) && (
          <div className="flex flex-wrap items-center gap-1 pt-0.5">
            {stockTags.map((t) => (
              <span key={`${t.entity_id}-${t.link_type}`} className="inline-flex items-center gap-0.5">
                <EntityChip tag={t} onFilter={onChipFilter} />
                {t.aliases && (
                  <Link
                    to={`/analyze/${t.aliases}/summary`}
                    className="text-[10px] text-muted-foreground hover:text-primary"
                    title="종목 상세로 이동"
                  >
                    ↗
                  </Link>
                )}
              </span>
            ))}
            {otherTags.map((t) => (
              <EntityChip key={`${t.entity_id}-${t.link_type}`} tag={t} onFilter={onChipFilter} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function FeedSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-6 w-24" />
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="border rounded-xl p-4 space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-40" />
        </div>
      ))}
    </div>
  )
}
