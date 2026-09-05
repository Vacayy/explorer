import { Link, useSearchParams } from "react-router-dom"
import { BellPlus, BellOff, Building2, Lightbulb, Loader2 } from "lucide-react"
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
import { Markdown } from "@/components/shared/Markdown"
import { PageContainer } from "@/components/shared/PageContainer"
import DigestSection from "@/components/analyze/DigestSection"

/**
 * /company?name= — 기업 프로필 (해외/비상장). 인물 프로필과 동형.
 * 국내 종목은 /analyze 종목 상세가 담당. 향후 해외 종목 데이터가 붙으면 확장.
 */
interface CompanyDossier {
  entity_id: number
  name: string
  listed: string | null
  category: string | null
  total_docs: number
  first_doc_at: string | null
  last_doc_at: string | null
  following: boolean
  profile: { status: string; digest: string | null; insights: string | null; created_at: string | null } | null
  profile_stale: boolean
  co_entities: { entity_id: number; name: string; link_type: string; aliases: string | null; count: number }[]
  recent_docs: { id: number; title: string; published_at: string | null }[]
}

const keys = {
  dossier: (n: string) => ["spine", "company", n] as const,
  profile: (n: string) => ["spine", "company", n, "profile"] as const,
}

export default function CompanyPage() {
  const [sp] = useSearchParams()
  const name = sp.get("name") ?? ""
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<CompanyDossier>({
      key: keys.dossier(name),
      url: `/api/spine/company/${encodeURIComponent(name)}/dossier`,
      staleTime: STALE.short, enabled: !!name,
    }),
  )
  const profile = useQuery(
    apiComputeQuery<NonNullable<CompanyDossier["profile"]>>({
      key: keys.profile(name),
      url: `/api/spine/company/${encodeURIComponent(name)}/profile`,
      enabled: !!data?.profile_stale,
    }),
  )
  const follow = useMutation({
    mutationFn: () => followEntity({ entity_id: data!.entity_id }),
    onSuccess: () => { toast.success(`'${name}' 팔로우`); qc.invalidateQueries({ queryKey: keys.dossier(name) }); qc.invalidateQueries({ queryKey: spineKeys.home() }) },
  })
  const unfollow = useMutation({
    mutationFn: () => unfollowEntity(data!.entity_id),
    onSuccess: () => { toast.success(`'${name}' 팔로우 해제`); qc.invalidateQueries({ queryKey: keys.dossier(name) }); qc.invalidateQueries({ queryKey: spineKeys.home() }) },
  })

  if (!name) return <ErrorState message="기업 이름이 없습니다 (?name= 필요)" />
  if (isLoading) return <PageContainer width="reading"><Skeleton className="h-7 w-56" /><Skeleton className="h-40 w-full rounded-xl" /></PageContainer>
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const p = profile.data ?? data.profile
  const stocks = data.co_entities.filter((e) => e.link_type === "stock")
  const people = data.co_entities.filter((e) => e.link_type === "person")
  const tags = data.co_entities.filter((e) => !["stock", "person"].includes(e.link_type))

  return (
    <PageContainer width="reading">
      <div className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-xl font-bold">{data.name}</h2>
          {data.listed && <Badge variant="secondary" className="text-[10px]">{data.listed}</Badge>}
          {data.category && <Badge variant="outline" className="text-[10px] text-muted-foreground">{data.category}</Badge>}
          <Button variant={data.following ? "outline" : "default"} size="xs" className="ml-auto"
            disabled={follow.isPending || unfollow.isPending}
            onClick={() => (data.following ? unfollow.mutate() : follow.mutate())}>
            {data.following ? <><BellOff className="h-3 w-3" /> 팔로우 해제</> : <><BellPlus className="h-3 w-3" /> 팔로우</>}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground tabular-nums">
          언급 {data.total_docs}건
          {data.first_doc_at && data.last_doc_at && ` · ${data.first_doc_at.slice(0, 10)} ~ ${data.last_doc_at.slice(0, 10)}`}
          {data.listed === "해외" && " · 해외 상장 (주가·재무 연동 예정)"}
        </p>
      </div>

      {data.total_docs === 0 ? (
        <EmptyState message="아직 이 기업이 언급된 수집 문서가 없습니다." />
      ) : (
        <>
          <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]">
            <CardHeader className="pb-2 flex-row items-baseline gap-2">
              <CardTitle className="text-sm">기업 프로필</CardTitle>
              {p?.created_at && <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{p.created_at.slice(0, 10)} 기준</span>}
            </CardHeader>
            <CardContent className="space-y-3">
              {profile.isFetching && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> 새 언급을 반영해 프로필 생성 중… (수십 초)
                </div>
              )}
              {p?.insights && (
                <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
                  <Lightbulb className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
                  <p className="text-xs"><span className="font-semibold text-hypothesis">지난 프로필 이후</span> {p.insights}</p>
                </div>
              )}
              {p?.digest && <Expandable collapsedHeight={280}><Markdown>{p.digest}</Markdown></Expandable>}
              {p?.digest && (
                <div className="text-right">
                  <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                    AI 프로필 · 열람 시점 갱신 — 검증 필요
                  </Badge>
                </div>
              )}
              {!p?.digest && !profile.isFetching && (
                <p className="text-xs text-muted-foreground py-1">
                  {profile.isError ? "프로필 생성 실패. 다시 열람하면 재시도됩니다." : "LLM 연결 시 열람 시점에 자동 생성됩니다."}
                </p>
              )}
            </CardContent>
          </Card>

          {data.co_entities.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">함께 언급되는 것</CardTitle></CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {stocks.map((e) => (
                  <Link key={`s-${e.entity_id}`}
                    to={e.aliases ? `/analyze/${e.aliases}/summary` : `/company?name=${encodeURIComponent(e.name)}`}>
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

          {/* 기간 요약 (D-124) — 종목코드가 없는 해외·비상장도 다이제스트를 받고 열람할 수 있게.
              백엔드가 코드·이름 겸용이라(D-124) DigestSection을 이름으로 그대로 재사용한다.
              진입 시 catch_up이 밀린 구간(오늘·이번 주)을 채운다 — cron은 닫힌 구간만 만든다. */}
          <DigestSection stockCode={name} stack />

          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">언급 문서</CardTitle></CardHeader>
            <CardContent className="divide-y">
              {data.recent_docs.map((d) => (
                <Link key={d.id} to={`/doc/${d.id}`} className="flex items-baseline gap-2 py-1.5 group">
                  <span className="text-sm truncate group-hover:underline">{d.title}</span>
                  <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">{(d.published_at ?? "").slice(0, 10)}</span>
                </Link>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </PageContainer>
  )
}
