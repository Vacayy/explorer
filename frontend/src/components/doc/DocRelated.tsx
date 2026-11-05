import { ErrorState } from "@/components/shared/ErrorState"
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { SourceBadge } from '@/components/shared/SourceBadge'
import { DetailLink as Link } from '@/components/shared/DetailNavigation'
import { useDocClaims, useRelatedDocs } from '@/hooks/useDocClaims'
import type { ClaimRelated, RelatedDoc } from '@/types'

/** 문서 상세 하단 관련 자료 — 논점별(D-233) + 유사도 기반(D-221). 논점에 나온 자료는 유사도 목록에서 뺀다. */
export function DocRelated({ docId }: { docId: number }) {
  const claims = useDocClaims(docId)
  const related = useRelatedDocs(docId)
  const status = claims.data?.status
  const groups = claims.data?.claims ?? []
  const shown = new Set(groups.flatMap((g) => g.related.map((r) => r.id)))
  const similar = (related.data ?? []).filter((r) => !shown.has(r.id)).slice(0, 3)
  const building = claims.isLoading || status === 'none' || status === 'running'
  if (!claims.isError && !related.isError && !building && status !== 'failed' && groups.length === 0 && similar.length === 0) return null
  return (
    <Card className="gap-3 rounded-[var(--radius-card)] p-4 shadow-none">
      <CardContent className="space-y-5 px-0">
        {claims.isError && <ErrorState error={claims.error} onRetry={() => void claims.refetch()} retrying={claims.isFetching} />}
        {related.isError && <ErrorState error={related.error} onRetry={() => void related.refetch()} retrying={related.isFetching} />}
        {(building || status === 'failed' || groups.length > 0) && (
          <section aria-live="polite">
            <h2 className="mb-1 text-[15px] leading-[1.4] font-semibold">이 자료의 논점별 관련 자료</h2>
            {building && (
              <div className="space-y-2">
                <p className="text-caption text-muted-foreground">논점을 정리하고 관련 자료를 찾는 중입니다. 아래 유사도 기반 자료는 먼저 볼 수 있습니다.</p>
                <Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" />
              </div>
            )}
            {status === 'failed' && (
              <div className="space-y-2">
                <p role="alert" className="text-sm text-destructive">{claims.data?.error}</p>
                <Button size="sm" variant="outline" disabled={claims.build.isPending} onClick={() => claims.build.mutate()}>다시 시도</Button>
              </div>
            )}
            {status === 'ok' && groups.length === 0 && <p className="text-caption text-muted-foreground">이 자료의 논점과 충분히 맞닿은 다른 자료를 아직 찾지 못했습니다.</p>}
            {/* 시안 Doc: 한 줄 = 논점(회색) · 자료 제목 · 인용 | 소스 배지 */}
            <ul>{groups.flatMap((g) => g.related.map((r) => <ClaimRow key={`${g.claim}-${r.id}`} claim={g.claim} r={r} />))}</ul>
          </section>
        )}
        {similar.length > 0 && (
          <section>
            <h2 className="mb-1.5 text-caption text-muted-foreground">유사도 기반 관련 자료</h2>
            <ul className="space-y-1.5">{similar.map((r) => <SimilarRow key={r.id} r={r} />)}</ul>
          </section>
        )}
      </CardContent>
    </Card>
  )
}

function Meta({ channel, published_at }: { channel: string | null; published_at: string | null }) {
  return (
    <span className="ml-auto shrink-0 text-muted-foreground tabular-nums max-md:ml-0">
      {channel && <span className="mr-1.5">{channel}</span>}
      {(published_at || '').slice(0, 10)}
    </span>
  )
}

function ClaimRow({ claim, r }: { claim: string; r: ClaimRelated }) {
  return (
    <li className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 border-t py-2.5 first:border-t-0">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-xs text-ink-3">‘{claim}’ 논점</span>
        <Link to={`/doc/${r.id}`} className="text-[13.5px] hover:underline">{r.title || '(제목 없음)'}</Link>
        {r.quote && <span className="line-clamp-2 text-[12.5px] text-ink-2">“{r.quote}”</span>}
      </div>
      <span className="flex flex-col items-end gap-1"><SourceBadge sourceType={r.source_type} /><span className="text-[11px] text-ink-3 tabular-nums">{(r.published_at || '').slice(0, 10)}</span></span>
    </li>
  )
}

function SimilarRow({ r }: { r: RelatedDoc }) {
  return (
    <li className="flex items-center gap-2 text-xs max-md:flex-wrap max-md:gap-y-1">
      <SourceBadge sourceType={r.source_type} />
      <Link to={`/doc/${r.id}`} className="min-w-0 truncate hover:underline max-md:order-first max-md:basis-full max-md:whitespace-normal max-md:line-clamp-2">{r.title || '(제목 없음)'}</Link>
      {r.reasons.length > 0 && (
        <span className="hidden shrink-0 gap-1 sm:flex" title="겹치는 종목·인물·산업">
          {r.reasons.map((n) => <Badge key={n} variant="outline" className="font-normal">{n}</Badge>)}
        </span>
      )}
      <Meta channel={r.channel} published_at={r.published_at} />
    </li>
  )
}
