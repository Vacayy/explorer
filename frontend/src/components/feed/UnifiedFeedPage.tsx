import { Timeline } from './Timeline'
import { DocumentCard } from './FeedPost'
import { isDocumentFeed } from '@/components/layout/navConfig'
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom"
import { BellPlus, Search, X } from "lucide-react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { followEntity, spineKeys } from "@/api/spine"
import { useSpineFeed } from "@/hooks/useSpineFeed"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import type { EntityTag } from "@/types"

/**
 * /feed — 통합 피드 (product-v2.md v2.1)
 * URL 쿼리 파라미터(source/stock/industry/topic/page)가 필터 상태의 단일 소스.
 * 엔티티 칩 클릭 = 해당 필터 적용.
 */
export default function UnifiedFeedPage() {
  const [params] = useSearchParams()
  if (isDocumentFeed(params.toString())) return <DocumentFeedPage />
  if ([...params.keys()].some(key => key.startsWith('feed_'))) return <PageLayout width="reading"><Timeline /></PageLayout>
  return <Navigate to="/home?home_view=feed" replace />
}

function DocumentFeedPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
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
  const qc = useQueryClient()
  const follow = useMutation({
    mutationFn: followEntity,
    onSuccess: (_d, v) => {
      toast.success(`'${v.name}' 팔로우 — 홈 업데이트에 반영됩니다`)
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })

  const setFilter = (key: string, value: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set("view", "documents")
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
    else if (tag.link_type === "person") navigate(`/person?name=${encodeURIComponent(tag.name)}`)
  }

  if (isLoading) return <FeedSkeleton />
  if (isError || !data) return <PageLayout header={<PageHeader title="문서 검색" />}><ErrorState onRetry={() => refetch()} /></PageLayout>

  const totalPages = Math.max(1, Math.ceil(data.total / data.size))
  const activeFilters = (["stock", "industry", "topic"] as const).filter((k) => filters[k])

  return (
    <PageLayout header={<PageHeader title="문서 검색" actions={<><Button asChild variant="ghost" size="sm"><Link to="/home?home_view=feed">Home 피드로</Link></Button><FreshnessStamp asOf={data.as_of} /></>} />}>
      <div className="space-y-4">

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
        <Input key={filters.q ?? ""} aria-label="문서 검색" autoComplete="off" name="q" defaultValue={filters.q ?? ""} placeholder="문서 검색 (의미 기반)…" className="pl-8 h-8 text-sm" />
        {filters.q && (
          <Button type="button" variant="ghost" size="sm" aria-label="검색어 지우기" onClick={() => setFilter("q", null)}
            className="h-fit border-0 p-0 absolute right-2.5 inset-y-0 my-auto text-muted-foreground hover:text-foreground hover:bg-transparent">
            <X className="size-3.5" />
          </Button>
        )}
      </form>

      {/* 활성 필터 칩 (제거 가능) */}
      {activeFilters.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-muted-foreground">필터:</span>
          {activeFilters.map((k) => (
            <Badge key={k} variant="secondary" className="text-xs gap-1 pr-1">
              {k === "stock" ? `종목 ${filters[k]}` : filters[k]}
              <Button variant="ghost" size="sm" className="h-auto border-0 p-0 hover:bg-transparent hover:text-inherit" onClick={() => setFilter(k, null)} aria-label="필터 제거">
                <X className="size-3" />
              </Button>
            </Badge>
          ))}
          {(filters.industry || filters.topic) && (
            <Button
              variant="outline" size="xs"
              disabled={follow.isPending}
              onClick={() => follow.mutate(filters.industry
                ? { type: "sector", name: filters.industry }
                : { type: "theme", name: filters.topic! })}
            >
              <BellPlus className="h-3 w-3" /> 이 태그 팔로우
            </Button>
          )}
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setSearchParams(filters.source ? { view: "documents", source: filters.source } : { view: "documents" })}
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
    </PageLayout>
  )
}

function FeedSkeleton() {
  return (
    <PageLayout header={<PageHeader title="문서 검색" />}>
      <div className="space-y-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="border rounded-xl p-4 space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-40" />
        </div>
      ))}
      </div>
    </PageLayout>
  )
}
