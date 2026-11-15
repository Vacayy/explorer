import { publicCompanyReturn, publicFeedUrl as feedUrl } from '@/lib/publicDocumentNavigation'
import { useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { toApiError } from '@/api/errors'
import { usePublishedDocuments } from '@/hooks/usePublishedDocuments'
import { PageContainer } from '@/components/shared/PageContainer'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function SearchForm({ q, onSearch }: { q: string; onSearch: (q: string) => void }) {
  const [draft, setDraft] = useState(q)
  return <form role="search" className="space-y-2" onSubmit={event => { event.preventDefault(); onSearch(draft.trim()) }}>
    <Label htmlFor="public-document-search">공개 문서 검색</Label>
    <div className="flex gap-2">
      <Input id="public-document-search" type="search" maxLength={120} value={draft} onChange={event => setDraft(event.target.value)} placeholder="제목 또는 본문 검색" />
      <Button type="submit">검색</Button>
    </div>
  </form>
}

export function PublicDocumentListPage() {
  const [params] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const q = (params.get('q') ?? '').trim()
  const cursor = params.get('cursor')
  const valid = q.length <= 120 && (cursor === null || (cursor.length > 0 && cursor.length <= 2048))
  const query = usePublishedDocuments(q, cursor, valid)
  const companyReturn = publicCompanyReturn(params.get('company_return'))
  const first = feedUrl(q, null, companyReturn)
  const returnTo = feedUrl(q, cursor, companyReturn)
  const previous = () => {
    if (location.state?.publicFeedPrevious === true) navigate(-1)
    else navigate(first)
  }
  const data = query.data
  return <PageContainer width="reading" className="[overflow-wrap:anywhere]">
    <header className="space-y-2"><h1 className="text-xl font-medium">공개 문서</h1><p className="text-sm text-ink-2">공개된 자료의 제목과 보관된 본문을 검색합니다.</p></header>
    <Button asChild variant="outline"><Link to="/chat">공개 자료 체험 채팅</Link></Button>
    {companyReturn && <div className="space-y-2"><Button asChild variant="outline"><Link to={companyReturn}>기업 요약으로</Link></Button><p className="text-sm text-ink-2">회사명으로 시작한 제목·본문 검색입니다. 검색 결과는 검증된 기업 관계나 추천을 뜻하지 않습니다.</p></div>}
    <SearchForm key={q} q={q.slice(0, 120)} onSearch={value => navigate(feedUrl(value, null, companyReturn))} />
    {!valid ? <ErrorState message="검색 주소를 확인해 주세요." />
      : query.error ? toApiError(query.error).status === 400
        ? <ErrorState message="이어서 볼 수 있는 시간이 지났거나 검색 주소가 올바르지 않습니다." onRetry={() => navigate(first)} />
        : <ErrorState message="공개 문서 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요." onRetry={() => void query.refetch()} retrying={query.isFetching} />
      : query.fetchStatus === 'paused' ? <ErrorState message="네트워크 연결을 확인해 주세요." onRetry={() => void query.refetch()} />
      : !data || query.isFetching ? <p role="status">공개 문서를 불러오는 중…</p>
      : <>
        {data.items.length === 0 ? <EmptyState message={data.next_cursor !== null ? (q ? '아직 일치하는 문서가 없습니다. 계속 검색할 수 있습니다.' : '이 구간에는 공개된 문서가 없습니다. 다음 목록을 확인해 주세요.') : q ? '검색 결과가 없습니다.' : cursor !== null ? '더 이상 공개된 문서가 없습니다.' : '아직 공개된 문서가 없습니다.'} />
          : <ul className="divide-y border-y">{data.items.map(item => <li key={item.id} className="space-y-2 py-5">
            <h2 className="text-base font-medium"><Link to={`/doc/${item.id}${returnTo === '/feed' ? '' : `?${new URLSearchParams({ return_to: returnTo })}`}`}>{item.title || '제목 없는 문서'}</Link></h2>
            {item.published_at && <p className="text-xs text-ink-2">{item.published_at}</p>}
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-2">{item.snippet || '보관된 본문 미리보기가 없습니다.'}</p>
          </li>)}</ul>}
        {data.next_cursor !== null && <div className="flex justify-end"><Button asChild variant="outline"><Link to={feedUrl(q, data.next_cursor, companyReturn)} state={{ publicFeedPrevious: true }}>다음</Link></Button></div>}
      </>}
    {cursor !== null && <nav aria-label="이전 문서 목록" className="flex flex-wrap gap-2">
      <Button variant="outline" onClick={previous}>이전</Button>
      <Button asChild variant="ghost"><Link to={first}>검색 처음부터</Link></Button>
    </nav>}
  </PageContainer>
}
