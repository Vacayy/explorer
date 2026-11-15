import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
import { usePublishedDocument } from '@/hooks/usePublishedDocument'
import { DocumentCardView } from '@/components/feed/FeedPost'
import { PublishedDocumentBody, safeExternalUrl } from '@/components/doc/PublicDocumentPage'
import { SourceBadge } from '@/components/shared/SourceBadge'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { toApiError } from '@/api/errors'
import { formatRelativeTime } from '@/utils/format'

/** Same feed card, backed only by the current approved document. */
export function PublishedDocumentCard({ id, returnTo = '/feed' }: { id: number; returnTo?: string }) {
  const query = usePublishedDocument(id)
  if (query.error) return toApiError(query.error).status === 404
    ? <EmptyState message="공개된 문서를 찾을 수 없습니다." />
    : <ErrorState message="문서를 불러오지 못했습니다." onRetry={() => void query.refetch()} />
  if (query.fetchStatus === 'paused') return <ErrorState message="네트워크 연결을 확인해 주세요." onRetry={() => void query.refetch()} />
  if (!query.data || query.isFetching) return <p role="status" className="feed-post-row">게시물 불러오는 중…</p>
  const doc = query.data
  const to = `/doc/${id}${returnTo === '/feed' ? '' : `?${new URLSearchParams({ return_to: returnTo })}`}`
  const sourceUrl = safeExternalUrl(doc.url)
  return <DocumentCardView title={doc.title || '제목 없는 게시물'} to={to}
    header={<div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
      <SourceBadge sourceType={doc.source_type} />
      <span className="min-w-0 truncate font-medium text-ink-2">{doc.channel?.name || '수집 자료'}</span>
      {doc.published_at && <time className="ml-auto shrink-0 text-caption" dateTime={doc.published_at} title={doc.published_at}>{formatRelativeTime(doc.published_at)} 게시</time>}
    </div>}
    body={<PublishedDocumentBody document={doc} />}
    actions={<>
      <Button asChild variant="ghost" size="sm" className="ml-auto"><Link to={to}>자료 상세<ArrowUpRight aria-hidden="true" /></Link></Button>
      {sourceUrl && <Button asChild variant="outline" size="sm"><a href={sourceUrl} target="_blank" rel="noopener noreferrer"><span>원문<span className="max-md:hidden"> 사이트</span></span><ArrowUpRight aria-hidden="true" /></a></Button>}
    </>} />
}
