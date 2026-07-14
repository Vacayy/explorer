import { Link, useSearchParams } from "react-router-dom"
import { Markdown } from "@/components/shared/Markdown"
import { BellPlus, BellOff, Lightbulb, Loader2, User } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { followEntity, unfollowEntity, spineKeys } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { Expandable } from "@/components/shared/Expandable"
import { PageContainer } from "@/components/shared/PageContainer"

/**
 * /person?name= — 인물 도시에 (knowledge-system.md ③).
 * 언급·발언 흐름 + 연관 엔티티(파급 경로) + 게으른 프로필 + 팔로우.
 * 프로필은 (kind='person') source_digests 재사용 — 소스 도시에와 동일 규율.
 */

interface PersonDossier {
  entity_id: number
  name: string
  total_docs: number
  first_doc_at: string | null
  last_doc_at: string | null
  following: boolean
  profile: { status: string; digest: string | null; insights: string | null; created_at: string | null } | null
  profile_stale: boolean
  co_entities: { entity_id: number; name: string; link_type: string; aliases: string | null; count: number }[]
  recent_docs: { id: number; title: string; published_at: string | null }[]
}

const personKeys = {
  dossier: (name: string) => ["spine", "person", name] as const,
  profile: (name: string) => ["spine", "person", name, "profile"] as const,
}

export default function PersonPage() {
  const [searchParams] = useSearchParams()
  const name = searchParams.get("name") ?? ""
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<PersonDossier>({
      key: personKeys.dossier(name),
      url: `/api/spine/person/${encodeURIComponent(name)}/dossier`,
      staleTime: STALE.short,
      enabled: !!name,
    }),
  )
  const profile = useQuery(
    apiComputeQuery<NonNullable<PersonDossier["profile"]>>({
      key: personKeys.profile(name),
      url: `/api/spine/person/${encodeURIComponent(name)}/profile`,
      enabled: !!data?.profile_stale,
    }),
  )
  const follow = useMutation({
    mutationFn: () => followEntity({ entity_id: data!.entity_id }),
    onSuccess: () => {
      toast.success(`'${name}' 팔로우 — 홈 업데이트에 반영됩니다`)
      qc.invalidateQueries({ queryKey: personKeys.dossier(name) })
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })
  const unfollow = useMutation({
    mutationFn: () => unfollowEntity(data!.entity_id),
    onSuccess: () => {
      toast.success(`'${name}' 팔로우 해제`)
      qc.invalidateQueries({ queryKey: personKeys.dossier(name) })
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })

  if (!name) return <ErrorState message="인물 이름이 없습니다 (?name= 필요)" />
  if (isLoading) return <PersonSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const p = profile.data ?? data.profile
  const stocks = data.co_entities.filter((e) => e.link_type === "stock")
  const people = data.co_entities.filter((e) => e.link_type === "person")
  const tags = data.co_entities.filter((e) => !["stock", "person"].includes(e.link_type))

  return (
    <PageContainer width="reading">
      {/* 헤더 */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <User className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-xl font-bold">{data.name}</h2>
          <Badge variant="secondary" className="text-[10px]">인물</Badge>
          <Button
            variant={data.following ? "outline" : "default"} size="xs" className="ml-auto"
            disabled={follow.isPending || unfollow.isPending}
            onClick={() => (data.following ? unfollow.mutate() : follow.mutate())}
          >
            {data.following ? <><BellOff className="h-3 w-3" /> 팔로우 해제</> : <><BellPlus className="h-3 w-3" /> 팔로우</>}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground tabular-nums">
          언급 {data.total_docs}건
          {data.first_doc_at && data.last_doc_at &&
            ` · ${data.first_doc_at.slice(0, 10)} ~ ${data.last_doc_at.slice(0, 10)}`}
        </p>
      </div>

      {data.total_docs === 0 ? (
        <EmptyState message="아직 이 인물이 언급된 수집 문서가 없습니다." />
      ) : (
        <>
          {/* 인물 프로필 — 게으른 생성 */}
          <Card className="border-l-2 border-l-hypothesis">
            <CardHeader className="pb-2 flex-row items-baseline gap-2">
              <CardTitle className="text-sm">인물 프로필</CardTitle>
              {p?.created_at && (
                <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                  {p.created_at.slice(0, 10)} 기준
                </span>
              )}
            </CardHeader>
            <CardContent className="space-y-3">
              {profile.isFetching && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  새 언급을 반영해 프로필 생성 중… (수십 초)
                </div>
              )}
              {p?.insights && (
                <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
                  <Lightbulb className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
                  <p className="text-xs"><span className="font-semibold text-hypothesis">지난 프로필 이후</span> {p.insights}</p>
                </div>
              )}
              {p?.digest && (
                <Expandable collapsedHeight={280}>
                  <Markdown>{p.digest}</Markdown>
                </Expandable>
              )}
              {p?.digest && (
                <div className="text-right">
                  <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                    AI 프로필 · 열람 시점 갱신 — 검증 필요
                  </Badge>
                </div>
              )}
              {!p?.digest && !profile.isFetching && (
                <p className="text-xs text-muted-foreground py-1">
                  {profile.isError ? "프로필 생성에 실패했습니다. 다시 열람하면 재시도됩니다." : "LLM 연결 시 열람 시점에 자동 생성됩니다."}
                </p>
              )}
            </CardContent>
          </Card>

          {/* 파급 경로 — 이 인물과 함께 언급되는 것들 */}
          {data.co_entities.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">함께 언급되는 것</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {stocks.map((e) => (
                  <Link key={`s-${e.entity_id}`}
                    to={e.aliases ? `/analyze/${e.aliases}/summary` : `/feed?q=${encodeURIComponent(e.name)}`}>
                    <Badge variant="outline" className="text-xs gap-1 hover:border-primary hover:text-primary">
                      {e.name} <span className="text-muted-foreground tabular-nums">{e.count}</span>
                    </Badge>
                  </Link>
                ))}
                {people.map((e) => (
                  <Link key={`p-${e.entity_id}`} to={`/person?name=${encodeURIComponent(e.name)}`}>
                    <Badge variant="outline" className="text-xs gap-1 text-hypothesis border-hypothesis/40 hover:bg-hypothesis/10">
                      {e.name} <span className="tabular-nums">{e.count}</span>
                    </Badge>
                  </Link>
                ))}
                {tags.map((e) => (
                  <Link key={`t-${e.entity_id}-${e.link_type}`}
                    to={`/feed?${e.link_type === "industry" ? "industry" : "topic"}=${encodeURIComponent(e.name)}`}>
                    <Badge variant="secondary" className="text-xs gap-1 hover:text-primary">
                      {e.name} <span className="text-muted-foreground tabular-nums">{e.count}</span>
                    </Badge>
                  </Link>
                ))}
              </CardContent>
            </Card>
          )}

          {/* 언급·발언 문서 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">언급·발언</CardTitle>
            </CardHeader>
            <CardContent className="divide-y">
              {data.recent_docs.map((d) => (
                <Link key={d.id} to={`/doc/${d.id}`} className="flex items-baseline gap-2 py-1.5 group">
                  <span className="text-sm truncate group-hover:underline">{d.title}</span>
                  <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
                    {(d.published_at ?? "").slice(0, 10)}
                  </span>
                </Link>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </PageContainer>
  )
}

function PersonSkeleton() {
  return (
    <div className="space-y-4 max-w-3xl">
      <Skeleton className="h-7 w-56" />
      <Skeleton className="h-40 w-full rounded-xl" />
      <Skeleton className="h-20 w-full rounded-xl" />
    </div>
  )
}
