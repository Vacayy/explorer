import { publicFeedReturn, publicCompanyReturn } from '@/lib/publicDocumentNavigation'
import { MemberDocumentSaveButton } from '@/components/shared/MemberDocumentSaveButton'
import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { toApiError } from '@/api/errors'
import { usePublishedDocument } from '@/hooks/usePublishedDocument'
import { PageContainer } from '@/components/shared/PageContainer'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { Markdown } from '@/components/shared/Markdown'
import { Button } from '@/components/ui/button'
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
  return <DocumentContainer>
    <header className="space-y-2">
      <h1 className="text-xl font-medium">{document.title || '제목 없는 문서'}</h1>
      <MemberDocumentSaveButton docId={id} />
      <Button asChild variant="outline" size="sm"><Link to="/feed/saved">내 저장 목록</Link></Button>
      <Button asChild variant="outline" size="sm"><Link to={`/chat?doc=${id}`}>이 문서로 체험 채팅</Link></Button>
      {sourceUrl && <Button asChild variant="outline" size="sm"><a href={sourceUrl} target="_blank" rel="noopener noreferrer">출처 페이지</a></Button>}
    </header>
    <PublishedDocumentBody document={document} />
  </DocumentContainer>
}

/** Approved text and document-bound attachments; never resolves raw /media or private document tools. */
export function PublishedDocumentBody({ document }: { document: PublishedDocument }) {
  const id = document.id
  const attachments = document.attachments.filter(attachment => Number.isSafeInteger(attachment.id) && attachment.id >= 0
    && attachment.url === `/api/public/documents/${id}/attachments/${attachment.id}`)
  return <>
    <section aria-label="보관된 본문" className="min-w-0 space-y-3">
      <h2 className="text-sm font-medium text-ink-2">보관된 본문</h2>
      {document.content.trim() ? document.content_kind === 'stored_markdown'
        ? <Markdown className="min-w-0 [&_pre]:overflow-x-auto" components={{
          img: () => null,
          a: ({ href, children }) => {
            const safe = safeExternalUrl(href)
            return safe ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>
          },
        }}>{document.content}</Markdown>
        : <div className="whitespace-pre-wrap text-sm leading-relaxed">{document.content}</div>
        : <p className="text-sm text-ink-2">보관된 본문이 없습니다.{attachments.length > 0 ? ' 아래 첨부를 확인해 주세요.' : ''}</p>}
    </section>
    {attachments.length > 0 && <section aria-label="공개 첨부" className="min-w-0 space-y-3">
      <h2 className="text-sm font-medium text-ink-2">공개 첨부</h2>
      {attachments.map((attachment, index) => <Attachment key={`${id}:${attachment.id}`} attachment={attachment} index={index} />)}
    </section>}
  </>
}
