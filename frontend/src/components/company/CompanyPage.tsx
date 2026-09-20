import { Link, useSearchParams } from 'react-router-dom'
import { BellPlus, BellOff, Building2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiQuery, STALE } from '@/api/query'
import { followEntity, unfollowEntity, spineKeys } from '@/api/spine'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import { CompanyEvidence } from './CompanyEvidence'
import { Markdown } from '@/components/shared/Markdown'
import { PageContainer } from '@/components/shared/PageContainer'

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
  profile: {
    status: string
    digest: string | null
    insights: string | null
    created_at: string | null
  } | null
  profile_stale: boolean
  co_entities: {
    entity_id: number
    name: string
    link_type: string
    aliases: string | null
    count: number
  }[]
  recent_docs: { id: number; title: string; published_at: string | null }[]
}

const keys = {
  dossier: (n: string) => ['spine', 'company', n] as const,
  profile: (n: string) => ['spine', 'company', n, 'profile'] as const,
}

export default function CompanyPage() {
  const [sp, setSp] = useSearchParams()
  const name = sp.get('name') ?? ''
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<CompanyDossier>({
      key: keys.dossier(name),
      url: `/api/spine/company/${encodeURIComponent(name)}/dossier`,
      staleTime: STALE.short,
      enabled: !!name,
    }),
  )
  const follow = useMutation({
    mutationFn: () => followEntity({ entity_id: data!.entity_id }),
    onSuccess: () => {
      toast.success(`'${name}' 팔로우`)
      qc.invalidateQueries({ queryKey: keys.dossier(name) })
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })
  const unfollow = useMutation({
    mutationFn: () => unfollowEntity(data!.entity_id),
    onSuccess: () => {
      toast.success(`'${name}' 팔로우 해제`)
      qc.invalidateQueries({ queryKey: keys.dossier(name) })
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })

  if (!name) return <ErrorState message="기업 이름이 없습니다 (?name= 필요)" />
  if (isLoading)
    return (
      <PageContainer width="reading">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </PageContainer>
    )
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const p = data.profile
  const stocks = data.co_entities.filter((e) => e.link_type === 'stock')
  const people = data.co_entities.filter((e) => e.link_type === 'person')
  const tags = data.co_entities.filter(
    (e) => !['stock', 'person'].includes(e.link_type),
  )

  return (
    <PageContainer width="reading">
      <div className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-xl font-bold">{data.name}</h2>
          {data.listed && (
            <Badge variant="secondary" className="text-[10px]">
              {data.listed}
            </Badge>
          )}
          {data.category && (
            <Badge
              variant="outline"
              className="text-[10px] text-muted-foreground"
            >
              {data.category}
            </Badge>
          )}
          <Button
            variant={data.following ? 'outline' : 'default'}
            size="xs"
            className="ml-auto"
            disabled={follow.isPending || unfollow.isPending}
            onClick={() =>
              data.following ? unfollow.mutate() : follow.mutate()
            }
          >
            {data.following ? (
              <>
                <BellOff className="h-3 w-3" /> 팔로우 해제
              </>
            ) : (
              <>
                <BellPlus className="h-3 w-3" /> 팔로우
              </>
            )}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground tabular-nums">
          언급 {data.total_docs}건
          {data.first_doc_at &&
            data.last_doc_at &&
            ` · ${data.first_doc_at.slice(0, 10)} ~ ${data.last_doc_at.slice(0, 10)}`}
          {data.listed === '해외' && ' · 해외 상장 (주가·재무 연동 예정)'}
        </p>
      </div>

      <nav aria-label="기업 상세" className="flex gap-2">
        {[
          ['overview', '개요'],
          ['business', '사업'],
          ['evidence', '자료'],
        ].map(([key, label]) => (
          <Button
            key={key}
            variant={
              (sp.get('tab') || 'overview') === key ? 'default' : 'outline'
            }
            onClick={() => setSp({ name, tab: key })}
          >
            {label}
          </Button>
        ))}
      </nav>
      {(sp.get('tab') || 'overview') === 'overview' && (
        <>
          <p className="text-sm">
            {data.category || '사업 분류 미확보'} · 주가·분기 재무 데이터가
            연결되지 않은 기업입니다.
          </p>
          <CompanyEvidence key={name} company={name} preview />
        </>
      )}
      {sp.get('tab') === 'evidence' && (
        <CompanyEvidence key={name} company={name} />
      )}
      {sp.get('tab') === 'business' &&
        (data.total_docs === 0 ? (
          <EmptyState message="아직 이 기업이 언급된 수집 문서가 없습니다." />
        ) : (
          <>
            <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]">
              <CardHeader className="pb-2 flex-row items-baseline gap-2">
                <CardTitle className="text-sm">기업 프로필</CardTitle>
                {p?.created_at && (
                  <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                    {p.created_at.slice(0, 10)} 기준
                  </span>
                )}
              </CardHeader>
              <CardContent className="space-y-3">
                {p?.digest ? (
                  <>
                    <Markdown>{p.digest}</Markdown>
                    <p className="text-caption text-muted-foreground">
                      저장된 AI 프로필 · 원문 검증 필요 · 자동 갱신 없음
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    확보된 사업 설명이 없습니다. 수집 자료의 원문을 확인해
                    주세요.
                  </p>
                )}
              </CardContent>
            </Card>

            {data.co_entities.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">함께 언급되는 것</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-1.5">
                  {stocks.map((e) => (
                    <Link
                      key={`s-${e.entity_id}`}
                      to={
                        e.aliases
                          ? `/analyze/${e.aliases}/summary`
                          : `/company?name=${encodeURIComponent(e.name)}`
                      }
                    >
                      <Badge
                        variant="outline"
                        className="text-xs gap-1 hover:border-primary hover:text-primary"
                      >
                        {e.name}{' '}
                        <span className="text-muted-foreground tabular-nums">
                          {e.count}
                        </span>
                      </Badge>
                    </Link>
                  ))}
                  {people.map((e) => (
                    <Link
                      key={`p-${e.entity_id}`}
                      to={`/person?name=${encodeURIComponent(e.name)}`}
                    >
                      <Badge
                        variant="outline"
                        className="text-xs gap-1 text-hypothesis border-hypothesis/40 hover:bg-hypothesis/10"
                      >
                        {e.name} <span className="tabular-nums">{e.count}</span>
                      </Badge>
                    </Link>
                  ))}
                  {tags.map((e) => (
                    <Link
                      key={`t-${e.entity_id}-${e.link_type}`}
                      to={`/feed?${e.link_type === 'industry' ? 'industry' : 'topic'}=${encodeURIComponent(e.name)}`}
                    >
                      <Badge
                        variant="secondary"
                        className="text-xs gap-1 hover:text-primary"
                      >
                        {e.name}{' '}
                        <span className="text-muted-foreground tabular-nums">
                          {e.count}
                        </span>
                      </Badge>
                    </Link>
                  ))}
                </CardContent>
              </Card>
            )}
          </>
        ))}
    </PageContainer>
  )
}
