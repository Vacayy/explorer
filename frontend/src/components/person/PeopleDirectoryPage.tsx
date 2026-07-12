import { Link, useSearchParams } from "react-router-dom"
import { Users } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import { formatRelativeTime } from "@/utils/format"
import { cn } from "@/lib/utils"

/**
 * /people — 인물 디렉토리 (탐색의 발견 표면).
 * 기업만큼 중요한 객체인 인물이 숨어 있지 않도록: 수집된 전체 인물을
 * 언급량 순으로 펼치고, 최근 발언·파급 종목을 한 줄에서 스캔 → 도시에로 depth.
 */

interface PersonRow {
  entity_id: number
  name: string
  doc_count: number
  last_doc_at: string | null
  last_doc_title: string | null
  last_doc_id: number | null
  following: boolean
  top_stocks: string[]
}

const PERIOD_FILTERS = [
  { key: 0, label: "전체" },
  { key: 30, label: "최근 30일" },
  { key: 7, label: "최근 7일" },
] as const

export default function PeopleDirectoryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const days = Number(searchParams.get("days") ?? "0")
  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<PersonRow[]>({
      key: ["spine", "people", days],
      url: `/api/spine/person?days=${days}`,
      staleTime: STALE.short,
    }),
  )

  if (isLoading) return <PeopleSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Users className="h-5 w-5 text-muted-foreground" /> 인물
        </h2>
        <span className="text-xs text-muted-foreground">{data.length}명 수집됨</span>
        <span className="ml-auto flex gap-1">
          {PERIOD_FILTERS.map((f) => (
            <Badge
              key={f.key}
              variant={days === f.key ? "default" : "outline"}
              className="cursor-pointer select-none text-xs"
              onClick={() => setSearchParams(f.key ? { days: String(f.key) } : {})}
            >
              {f.label}
            </Badge>
          ))}
        </span>
      </div>

      {data.length === 0 ? (
        <EmptyState message="해당 기간에 언급된 인물이 없습니다. 수집이 쌓이면 자동으로 나타납니다." />
      ) : (
        <Card>
          <CardContent className="divide-y">
            {data.map((p) => (
              <div key={p.entity_id} className="py-2.5 space-y-1">
                <div className="flex items-center gap-2">
                  <Link
                    to={`/person?name=${encodeURIComponent(p.name)}`}
                    className="font-semibold text-sm hover:underline hover:text-primary"
                  >
                    {p.name}
                  </Link>
                  {p.following && (
                    <Badge variant="outline" className="text-[9px] text-primary border-primary/40">팔로우 중</Badge>
                  )}
                  <span className="text-[11px] text-muted-foreground tabular-nums">언급 {p.doc_count}건</span>
                  <span className="ml-auto flex gap-1">
                    {p.top_stocks.map((s) => (
                      <Badge key={s} variant="secondary" className="text-[10px] font-normal">{s}</Badge>
                    ))}
                  </span>
                </div>
                {p.last_doc_title && (
                  <div className="flex items-baseline gap-2">
                    <Link
                      to={p.last_doc_id ? `/doc/${p.last_doc_id}` : "#"}
                      className={cn("text-xs text-muted-foreground truncate", p.last_doc_id && "hover:underline hover:text-foreground")}
                    >
                      최근 — {p.last_doc_title}
                    </Link>
                    <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
                      {formatRelativeTime(p.last_doc_at ?? "")}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </PageContainer>
  )
}

function PeopleSkeleton() {
  return (
    <PageContainer gap="sm">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-96 w-full rounded-xl" />
    </PageContainer>
  )
}
