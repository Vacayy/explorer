import { publicFeedReturn, publicCompanyReturn } from '@/lib/publicDocumentNavigation'
import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { toApiError } from '@/api/errors'
import { usePublishedDocument } from '@/hooks/usePublishedDocument'
import { PageContainer } from '@/components/shared/PageContainer'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { DocumentBody } from '@/components/doc/DocumentBody'
import { BoundedArea } from '@/components/shared/Bounded'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { Button } from '@/components/ui/button'
import { ChevronDown } from 'lucide-react'
import type { PublishedAttachment, PublishedDocument } from '@/types'

function DocumentContainer({ children }: { children: ReactNode }) {
  const [params] = useSearchParams()
  const company = publicCompanyReturn(params.get('return_to'))
  const back = company ?? publicFeedReturn(params.get('return_to'))
  return <PageContainer width="reading" className="[overflow-wrap:anywhere]">
    <Button asChild variant="ghost" size="sm" className="self-start"><Link to={back}>{company ? '기업 자료로 돌아가기' : '공개 문서 목록'}</Link></Button>
    {children}
  </PageContainer>
}

export function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value || !/^https?:\/\//i.test(value) || /[\u0000-\u0020\\]/.test(value)) return null
  try {
    const url = new URL(value)
    return url.username || url.password ? null : url.href
  } catch { return null }
}

function Attachment({ attachment, index }: { attachment: PublishedAttachment; index: number }) {
  const [failed, setFailed] = useState(false)
  if (attachment.media_type === 'application/pdf') {
    return <Button asChild variant="outline"><a href={attachment.url} download referrerPolicy="no-referrer">PDF 첨부 {index + 1} 다운로드</a></Button>
  }
  if (failed) return <p role="status" className="text-sm text-ink-2">첨부 이미지 {index + 1}을 불러올 수 없습니다.</p>
  return <img src={attachment.url} alt={`문서 첨부 이미지 ${index + 1}`} loading="lazy" referrerPolicy="no-referrer"
    className="h-auto max-w-full rounded-md" onError={() => setFailed(true)} />
}

export function PublicDocumentPage({ docId }: { docId: string }) {
  const [params, setParams] = useSearchParams()
  const id = /^[1-9]\d*$/.test(docId) && Number.isSafeInteger(Number(docId)) ? Number(docId) : null
  const query = usePublishedDocument(id)
  const retry = () => { void query.refetch() }
  // Never keep cached approved content visible after a failed revalidation/revocation.
  if (id === null || (query.error && toApiError(query.error).status === 404)) {
    return <DocumentContainer><EmptyState message="공개된 문서를 찾을 수 없습니다." /></DocumentContainer>
  }
  if (query.error) return <DocumentContainer><ErrorState message="공개 문서를 불러올 수 없습니다. 잠시 후 다시 시도해 주세요." retrying={query.isFetching} onRetry={retry} /></DocumentContainer>
  if (query.fetchStatus === 'paused') return <DocumentContainer><ErrorState message="네트워크 연결을 확인해 주세요." onRetry={retry} /></DocumentContainer>
  if (!query.data || query.isFetching) return <DocumentContainer><p role="status">공개 문서를 불러오는 중…</p></DocumentContainer>
  const document = query.data
  const sourceUrl = safeExternalUrl(document.url)
  const isVideo = document.source_type === 'youtube'
  const requested = params.get('reading')
  const reading = requested === 'summary' ? 'summary' : isVideo ? (requested === 'transcript' ? 'transcript' : 'digest') : 'original'
  return <DocumentContainer>
    <header className="space-y-2">
      <h1 className="text-xl font-medium">{document.title || '제목 없는 문서'}</h1>
      {sourceUrl && <Button asChild variant="outline" size="sm"><a href={sourceUrl} target="_blank" rel="noopener noreferrer">출처 페이지</a></Button>}
    </header>
    <SegmentTabs tabs={isVideo ? [{ value: 'digest', label: 'AI 정리본' }, { value: 'transcript', label: '원본 자막' }, { value: 'summary', label: '짧은 요약' }] : [{ value: 'original', label: '원문' }, { value: 'summary', label: '저장 요약' }]}
      value={reading} onChange={value => setParams(prev => { const next = new URLSearchParams(prev); next.set('reading', value); return next })} />
    <PublishedDocumentBody document={document} reading={reading} showToggle={false} />
  </DocumentContainer>
}

/** Approved text and document-bound attachments; never resolves raw /media or private document tools. */
export function PublishedDocumentBody({ document, reading = 'summary', showToggle = true }: { document: PublishedDocument; reading?: 'summary' | 'original' | 'digest' | 'transcript'; showToggle?: boolean }) {
  const id = document.id
  const [showOriginal, setShowOriginal] = useState(false)
  const hasSummary = !!document.summary?.trim()
  const attachments = document.attachments.filter(attachment => Number.isSafeInteger(attachment.id) && attachment.id >= 0
    && attachment.url === `/api/public/documents/${id}/attachments/${attachment.id}`)
  const hasOriginal = !!document.content.trim() || attachments.length > 0
  const doc = { source_type: document.source_type, content: document.content, summary: document.summary ?? null, images: [], video_digest: document.video_digest, transcript: document.transcript }
  const markdownComponents = { img: () => null, a: ({ href, children }: { href?: string; children?: ReactNode }) => {
    const safe = safeExternalUrl(href)
    return safe ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>
  } }
  const original = <>
    <section aria-label="보관된 본문" className="min-w-0 space-y-3">
      <DocumentBody doc={doc} reading="original" mediaSize={showToggle ? 'preview' : 'full'} markdownComponents={markdownComponents} />
    </section>
    {attachments.length > 0 && <section aria-label="공개 첨부" className="min-w-0 space-y-3">
      {attachments.map((attachment, index) => <Attachment key={`${id}:${attachment.id}`} attachment={attachment} index={index} />)}
    </section>}
  </>
  return <>
    {(reading === 'digest' || reading === 'transcript') && <DocumentBody doc={doc} reading={reading} markdownComponents={markdownComponents} />}
    {reading === 'summary' && (hasSummary || !showToggle) && <section aria-label="요약" className="min-w-0 space-y-3">
      <DocumentBody doc={doc} reading="summary" mediaSize="preview" markdownComponents={markdownComponents} />
      {showToggle && hasSummary && hasOriginal &&
      <Button variant="ghost" size="sm" className="-ml-2 text-caption text-ink-2" aria-expanded={showOriginal}
        onClick={() => setShowOriginal(value => !value)}>
        {showOriginal ? '원문 접기' : '원문 보기'}<ChevronDown aria-hidden="true" className={`size-3 transition-transform ${showOriginal ? 'rotate-180' : ''}`} />
      </Button>}
    </section>}
    {(reading === 'original' || (!hasSummary && showToggle)) && original}
    {reading === 'summary' && hasSummary && showToggle && showOriginal && <BoundedArea size="md" className="rounded-lg border border-line bg-surface-2/50" viewportClassName="p-3">{original}</BoundedArea>}
  </>
}
