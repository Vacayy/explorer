import { AddToStudy } from "@/components/study/AddToStudy"
import { StudyButton } from "@/components/study/StudyButton"
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useEffect, useRef } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink, MessageCircle } from 'lucide-react'
import api from '@/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { SourceBadge } from '@/components/shared/SourceBadge'
import { EntityChip } from '@/components/shared/EntityChip'
import { DetailLayout, DetailSection } from '@/components/shared/DetailLayout'
import { DetailLink as Link } from '@/components/shared/DetailNavigation'
import SegmentTabs from '@/components/shared/SegmentTabs'
import SaveButton from '@/components/shared/SaveButton'
import { SourceDeepDive } from './SourceDeepDive'
import { DocumentBody } from './DocumentBody'
import { useReadingDiscussion } from '@/hooks/useMemoryReading'
import { formatRelativeTime } from '@/utils/format'
import type { EntityTag, FeedDocument } from '@/types'

export default function DocPage() {
  const { docId } = useParams<{ docId: string }>()
  const navigate = useNavigate(), location = useLocation()
  const [params, setParams] = useSearchParams()
  const attempted = useRef(new Set<number>())
  const discussion = useReadingDiscussion()
  const { data: doc, isLoading, isError, refetch } = useQuery({
    queryKey: ['spine', 'doc', docId],
    queryFn: async () => (await api.get<FeedDocument>(`/api/spine/doc/${docId}`)).data,
    enabled: !!docId, staleTime: 5 * 60_000,
    refetchInterval: query => query.state.data?.digest_status === 'generating' ? 2000 : false,
  })
  const digest = useMutation({
    mutationFn: async (id: number) => { await api.post(`/api/spine/doc/${id}/digest`) },
    onSuccess: () => { void refetch() },
  })
  useEffect(() => {
    if (doc?.source_type === 'youtube' && (!doc.digest_status || doc.digest_status === 'pending') &&
        (doc.transcript?.length ?? 0) >= 100 && !attempted.current.has(doc.id)) {
      attempted.current.add(doc.id)
      digest.mutate(doc.id)
    }
  }, [doc?.id, doc?.digest_status])
  const isVideo = doc?.source_type === 'youtube'
  const reading = params.get('reading') === 'summary' ? 'summary' :
    isVideo ? (params.get('reading') === 'transcript' ? 'transcript' : 'digest') : 'original'
  const fallback = doc?.channel_kind && doc.channel_key ? `/source?kind=${doc.channel_kind}&key=${encodeURIComponent(doc.channel_key)}` : '/home?home_view=feed'
  if (isLoading || isError || !doc) return <DetailLayout title={isLoading ? '자료 불러오는 중' : '자료를 열 수 없습니다'} fallback="/home?home_view=feed" backLabel="피드로 돌아가기">
    {isLoading ? <Skeleton className="h-64 w-full" /> : <ErrorState message="문서를 불러오지 못했습니다." onRetry={() => void refetch()} />}
  </DetailLayout>
  const onChipFilter = (tag: EntityTag) => {
    if (tag.link_type === 'stock' && tag.aliases) navigate(/^\d{6}$/.test(tag.aliases) ? `/analyze/${tag.aliases}/summary` : `/us/${encodeURIComponent(tag.aliases)}`)
    else if (tag.link_type === 'stock') navigate(`/company?name=${encodeURIComponent(tag.name)}`)
    else if (tag.link_type === 'person') navigate(`/person?name=${encodeURIComponent(tag.name)}`)
    else navigate(`/feed?${tag.link_type === 'industry' ? 'industry' : 'topic'}=${encodeURIComponent(tag.name)}`)
  }
  return <DetailLayout title={doc.title || '제목 없는 자료'} fallback={fallback} backLabel={doc.channel_key ? '출처로 돌아가기' : '피드로 돌아가기'}
    context={<><SourceBadge sourceType={doc.source_type} />{doc.channel && <Link to={fallback} className="hover:underline">{doc.channel}</Link>}{doc.published_at && <time dateTime={doc.published_at} title={doc.published_at}>{formatRelativeTime(doc.published_at)} 게시</time>}</>}
    actions={<><StudyButton documentId={doc.id} /><AddToStudy documentId={doc.id} /><SaveButton kind="doc" refId={String(doc.id)} url={`/doc/${doc.id}`} title={doc.title} subtitle={doc.channel || doc.source_type} showLabel />
      <Button variant="ghost" size="sm" disabled={discussion.isPending || !doc.content?.trim()} onClick={() => discussion.mutate({ question: '이 자료의 핵심 주장과 근거, 확인이 필요한 점을 정리해줘.', ids: [doc.id] })}><MessageCircle aria-hidden="true" />{discussion.isPending ? '대화 준비 중' : '이 자료로 대화'}</Button>
      {/^https?:\/\//i.test(doc.url) && <Button asChild variant="outline" size="sm"><a href={doc.url} target="_blank" rel="noreferrer">원문 사이트<ExternalLink aria-hidden="true" /></a></Button>}</>}
    navigation={<SegmentTabs tabs={isVideo ? [{ value: 'digest', label: 'AI 정리본' }, { value: 'transcript', label: '원본 자막' }, { value: 'summary', label: '짧은 요약' }] : [{ value: 'original', label: '원문' }, { value: 'summary', label: '저장 요약' }]} value={reading} onChange={value => setParams(prev => { const next = new URLSearchParams(prev); next.set('reading', value); return next }, { replace: true, state: location.state })} />}
    aside={<><h2 className="mb-3 text-section font-semibold">이 자료의 맥락</h2><p className="mb-4 text-caption text-muted-foreground">개별 출처의 자료입니다. 시스템의 종합 해석과 구분해 읽으세요.</p>
      <h3 className="mb-2 text-card-title font-semibold">연결된 대상</h3><div className="mb-4 flex flex-wrap gap-2">{doc.entities.length ? doc.entities.map(tag => <EntityChip key={`${tag.entity_id}-${tag.link_type}`} tag={tag} onFilter={onChipFilter} />) : <p className="text-caption text-muted-foreground">연결된 대상이 없습니다.</p>}</div>
      <DetailSection title="출처·생성 정보"><p className="break-words text-caption text-muted-foreground">게시 시각: {doc.published_at || '미상'}</p>{doc.enrich_model && <p className="text-caption text-muted-foreground">태깅 모델: {doc.enrich_model}</p>}</DetailSection>
      <DetailSection title="추가 탐구"><p className="text-caption text-muted-foreground">이 자료에서 질문 후보를 생성합니다.</p><SourceDeepDive docId={doc.id} /></DetailSection></>}
    related={<RelatedSection docId={doc.id} />}>
    {discussion.isError && <p role="alert" className="mb-3 text-sm text-destructive">대화를 시작하지 못했습니다. 다시 시도해 주세요.</p>}
    {isVideo && !doc.video_digest && <div className="mb-4 rounded-xl border bg-muted/40 p-4 text-sm" aria-live="polite">
      <p>{digest.isPending || doc.digest_status === 'generating' ? 'AI 정리본을 만드는 중입니다. 원본 자막과 짧은 요약은 지금 읽을 수 있습니다.' :
        doc.digest_status === 'interrupted' ? '이전 생성이 중단되었습니다. 다시 시도해 주세요.' :
        doc.digest_error || (doc.digest_status === 'failed' ? '이전 AI 정리본 생성에 실패했습니다. 다시 시도할 수 있습니다.' : '아직 긴 AI 정리본이 없습니다.')}</p>
      {doc.digest_status !== 'generating' && <Button className="mt-2" size="sm" variant="outline" disabled={digest.isPending || (doc.transcript?.length ?? 0) < 100} onClick={() => digest.mutate(doc.id)}>AI 정리본 {doc.digest_status === 'failed' || doc.digest_status === 'interrupted' ? '다시 생성' : '생성'}</Button>}
      {digest.isError && <p role="alert" className="mt-2 text-destructive">생성 요청을 보내지 못했습니다. 다시 시도해 주세요.</p>}
    </div>}
    <DocumentBody doc={doc} reading={reading} />
  </DetailLayout>
}

function RelatedSection({ docId }: { docId: number }) {
  const { data } = useQuery({
    queryKey: ["spine", "doc", docId, "related"],
    queryFn: async () =>
      (await api.get(`/api/spine/doc/${docId}/related`)).data as {
        id: number; source_type: string; title: string | null; published_at: string | null
      }[],
    staleTime: 10 * 60_000,
  })
  if (!data || data.length === 0) return null
  return (
    <Card>
      <CardContent className="py-3">
        <div className="text-caption text-muted-foreground mb-1.5">관련 문서 (의미 유사)</div>
        <ul className="space-y-1">
          {data.map((r) => (
            <li key={r.id} className="flex items-center gap-2 text-xs">
              <SourceBadge sourceType={r.source_type} />
              <Link to={`/doc/${r.id}`} className="truncate hover:underline">{r.title || "(제목 없음)"}</Link>
              <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                {(r.published_at || "").slice(0, 10)}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
