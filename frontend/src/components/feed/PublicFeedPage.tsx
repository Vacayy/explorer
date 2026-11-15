import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, Search, X } from 'lucide-react'
import { FeedFrame, FeedHeaderView } from '@/components/feed/FeedPage'
import { ChannelReaderFrame, ChannelEntry, EntryButton } from '@/components/feed/ChannelReader'
import { PublishedDocumentCard } from '@/components/feed/PublishedDocumentCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import { usePublicFeed } from '@/hooks/usePublicFeed'
import { FEED_PLATFORMS } from '@/lib/feed'
import { sessionMemory } from '@/lib/sessionMemory'
import { sourceLabel } from '@/components/shared/SourceBadge'
import { formatNumber } from '@/utils/format'

const positions = sessionMemory<number>('explorer.public.reader.positions')
const labels: Record<string, string> = { ...FEED_PLATFORMS, sec: 'SEC 공시', sec_filing: 'SEC 공시', web: '웹', other: '기타' }

/** Original feed shell and source rows; only reviewed publication queries are mounted. */
export function PublicFeedPage() {
  const [params, setParams] = useSearchParams()
  const [snapshot] = useState(() => new Date().toISOString())
  const until = params.get('reader_until') || snapshot
  const channel = params.get('channel') || ''
  const platform = params.get('channel_type') || 'all'
  const topic = params.get('reader_topic') || ''
  const page = Math.max(1, Math.min(2000, Math.floor(Number(params.get('reader_page'))) || 1))
  const search = params.get('channel_q') || ''
  const readerOpen = params.get('reader_open') === '1' || (!params.has('reader_open') && !!channel)
  const query = usePublicFeed({ channel, platform, topic, page, until })
  // Never retain old approved titles or bodies after failed revalidation.
  const data = !query.error && !query.isFetching && query.fetchStatus !== 'paused' ? query.data : undefined
  const selected = data?.channels.find(item => item.id === channel)
  const reader = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const focus = useRef<'heading' | 'list' | null>(null)
  const positionKey = `${platform}:${channel}:${topic}:${page}`
  const listKey = `directory:${platform}:${search}`
  const patch = (values: Record<string, string | null>, replace = false) => setParams(prev => {
    const next = new URLSearchParams(prev)
    for (const [key, value] of Object.entries(values)) value === null ? next.delete(key) : next.set(key, value)
    return next
  }, { replace })
  useEffect(() => {
    if (!params.has('reader_until')) setParams(prev => {
      const next = new URLSearchParams(prev); next.set('reader_until', snapshot); return next
    }, { replace: true })
  }, [params, setParams, snapshot])
  useLayoutEffect(() => {
    if (data && list.current) list.current.scrollTop = positions.get(listKey) || 0
    if (data && reader.current) reader.current.scrollTop = positions.get(positionKey) || 0
    if (focus.current === 'heading' && readerOpen) { heading.current?.focus({ preventScroll: true }); focus.current = null }
    if (focus.current === 'list' && !readerOpen) { list.current?.querySelector<HTMLElement>('[aria-pressed="true"]')?.focus({ preventScroll: true }); focus.current = null }
  }, [data, listKey, positionKey, readerOpen])
  const select = (id: string) => {
    focus.current = 'heading'
    patch({ channel: id || null, reader_page: null, reader_topic: null, reader_open: '1' })
  }
  const paginate = (next: number) => { focus.current = 'heading'; patch({ reader_page: String(next), reader_open: '1' }) }
  const entries = data?.channels.filter(item => (platform === 'all' || item.platform === platform)
    && `${item.name} ${item.id}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())) ?? []
  const platforms = [...new Set([...Object.keys(FEED_PLATFORMS).filter(p => p !== 'system'), ...(data?.channels.map(c => c.platform) ?? [])])]
  const title = channel ? selected?.name || '선택한 소스' : platform === 'all' ? '소스 전체' : `${labels[platform] || sourceLabel(platform)} 전체`
  const failure = query.error || query.fetchStatus === 'paused'
  const loading = !failure && !data
  const returnTo = `/feed?${params}`
  return <FeedFrame searching={false} header={<FeedHeaderView searching={false} onView={v => setParams(v === 'documents' ? { view: 'documents' } : {})} />}>
    <ChannelReaderFrame readerOpen={readerOpen} directory={<>
      <div className="flex-none space-y-2 border-b p-3">
        <div className="flex items-center justify-between gap-2"><h2 className="text-section font-semibold">피드</h2></div>
        <div className="relative">
          <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" />
          <Input aria-label="소스 검색" placeholder="채널, 기업, 인물 검색" value={search} onChange={e => patch({ channel_q: e.target.value || null }, true)} className="pl-9" />
        </div>
        <div role="group" aria-label="소스 종류" className="flex min-w-0 flex-wrap gap-1">
          {['all', ...platforms].map(value => <Button key={value} variant={platform === value ? 'secondary' : 'ghost'} size="sm" aria-pressed={platform === value}
            className="shrink-0 px-2 text-caption" onClick={() => patch({ channel_type: value === 'all' ? null : value, channel: null, reader_topic: null, reader_page: null })}>{value === 'all' ? '전체' : labels[value] || sourceLabel(value)}</Button>)}
        </div>
      </div>
      <div ref={list} tabIndex={0} aria-label="소스 목록 스크롤" className="min-h-0 flex-1 p-2 md:overflow-y-auto md:overscroll-y-contain"
        onScroll={event => { if (data) positions.set(listKey, event.currentTarget.scrollTop) }}>
        <EntryButton selected={!channel} onClick={() => select('')}><span className="min-w-0 flex-1 text-left"><span className="block font-semibold">소스 전체</span><span className="block text-caption text-ink-3">공개된 수집 자료</span></span></EntryButton>
        {loading && <div role="status" aria-label="소스 불러오는 중" className="space-y-2 p-2">{[1,2,3].map(i => <Skeleton key={i} className="h-[72px] w-full" />)}</div>}
        {failure && <ErrorState message="소스 목록을 불러오지 못했습니다." onRetry={() => void query.refetch()} />}
        {entries.map(item => <ChannelEntry key={item.id} item={{ ...item, unread: 0 }} selected={channel === item.id} onSelect={() => select(item.id)} />)}
        {data && !entries.length && <EmptyState message={search || platform !== 'all' ? '조건에 맞는 소스가 없습니다.' : '아직 공개된 소스가 없습니다.'} />}
      </div>
    </>}>
      <header className="flex flex-none flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
        <Button variant="ghost" size="icon" className="shrink-0 md:hidden" aria-label="소스 목록으로" onClick={() => { focus.current = 'list'; patch({ reader_open: '0' }) }}><ArrowLeft aria-hidden="true" /></Button>
        <div className="min-w-0 flex-1">
          <h2 id="reader-title" ref={heading} tabIndex={-1} className="truncate text-section font-semibold outline-offset-4">{title}</h2>
          <p className="flex flex-wrap items-center gap-x-1 text-caption text-ink-3">{selected ? `${labels[selected.platform] || sourceLabel(selected.platform)} · 저장 ${formatNumber(selected.count)}건 · ` : ''}최신순</p>
        </div>
        <Button variant="ghost" size="icon" aria-label="피드 새로고침" disabled={query.isFetching} onClick={() => patch({ reader_until: new Date().toISOString(), reader_page: null })}><RefreshCw aria-hidden="true" className={query.isFetching ? 'animate-spin' : ''} /></Button>
      </header>
      {topic && <div className="border-b px-4 py-2.5"><Button variant="secondary" size="xs" onClick={() => patch({ reader_topic: null, reader_page: null })} aria-label={`주제 ${topic} 해제`}>{topic}<X aria-hidden="true" /></Button></div>}
      <div ref={reader} tabIndex={0} aria-label="게시물 스크롤" className="min-h-0 flex-1 md:overflow-y-auto md:overscroll-y-contain"
        onScroll={event => { if (data) positions.set(positionKey, event.currentTarget.scrollTop) }}>
        <div className="mx-auto max-w-[860px] px-6 pt-2 pb-6 max-md:px-4" aria-busy={query.isFetching}>
          {loading && <div role="status" aria-label="게시물 불러오는 중" className="space-y-4 pt-4">{[1,2,3].map(i => <Skeleton key={i} className="h-48 w-full" />)}</div>}
          {failure && <ErrorState message="게시물을 불러오지 못했습니다." onRetry={() => void query.refetch()} />}
          {data?.items.map(item => <PublishedDocumentCard key={item.id} id={item.id} returnTo={returnTo} />)}
          {data && !data.items.length && <EmptyState message={data.channels.length ? '이 페이지에서 현재 확인 가능한 게시물이 없습니다.' : '아직 공개된 게시물이 없습니다.'} />}
          {data && <nav className="flex flex-wrap items-center justify-between gap-3 border-t pt-5" aria-label="게시물 페이지">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => paginate(page - 1)}><ChevronLeft aria-hidden="true" />이전</Button>
            <span className="text-caption text-ink-3" role="status">{page}페이지{!data.has_more && ' · 마지막'}</span>
            <Button variant="outline" size="sm" disabled={!data.has_more || page >= 2000} onClick={() => paginate(page + 1)}>다음<ChevronRight aria-hidden="true" /></Button>
            {page >= 2000 && data.has_more && <p className="w-full text-caption text-ink-3">더 이전 자료는 <Link to="/feed?view=documents" className="underline">문서 검색</Link>에서 확인하세요.</p>}
          </nav>}
        </div>
      </div>
    </ChannelReaderFrame>
  </FeedFrame>
}
