import { sessionMemory } from "@/lib/sessionMemory"
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { DocumentCard, SystemPost } from './FeedPost'
import { useTimeline, useTimelineChannels } from '@/hooks/useTimeline'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import type { TimelineChannel } from '@/types'

const platforms = { telegram: '텔레그램', blog: '블로그', youtube: '유튜브', system: 'Explorer' }
function channelLabel(item: TimelineChannel) {
  const kind = { company: '기업 요약', person: '인물 요약', transcript: '컨콜', trade: '수출입' }[item.id.split(':')[0]]
  return item.platform === 'system' && kind ? `Explorer · ${kind}` : platforms[item.platform]
}
// UI-only positions. No inferred unread state and no writes to the document corpus.
const scrollPositions = sessionMemory<number>('explorer.reader.positions')

export function ChannelReader() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [initialSnapshot] = useState(() => new Date().toISOString())
  const until = params.get('reader_until') || initialSnapshot
  const channel = params.get('channel') || ''
  const reading = params.get('reading') === 'summary' ? 'summary' : 'original'
  const page = Math.max(1, Math.min(100, Math.floor(Number(params.get('reader_page'))) || 1))
  const query = params.get('channel_q') || ''
  const requestedPlatform = params.get('channel_type') || 'all'
  const platform = Object.hasOwn(platforms, requestedPlatform) ? requestedPlatform as keyof typeof platforms : 'all'
  const readerOpen = params.get('reader_open') === '1' || (!params.has('reader_open') && !!channel)
  const directory = useTimelineChannels(until)
  const timeline = useTimeline({ scope: platform === 'system' ? 'system' : platform === 'all' ? 'all' : 'sources', kind: 'all', source: platform === 'system' ? 'all' : platform, channel: channel || undefined, page, until })
  const selected = directory.data?.items.find(item => item.id === channel)
  const entries = (directory.data?.items || []).filter(item =>
    (platform === 'all' || item.platform === platform) &&
    `${item.name} ${item.id}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const heading = useRef<HTMLHeadingElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const reader = useRef<HTMLDivElement>(null)
  const focusTarget = useRef<'heading' | 'list' | null>(null)
  const positionKey = `${platform}:${channel}:${page}:${reading}`
  const listKey = `directory:${platform}:${query}`
  const patch = (values: Record<string, string | null>, replace = false) => setParams(prev => {
    const next = new URLSearchParams(prev)
    Object.entries(values).forEach(([key, value]) => value == null ? next.delete(key) : next.set(key, value))
    return next
  }, { replace })

  useEffect(() => {
    if (!params.has('reader_until')) setParams(prev => {
      const next = new URLSearchParams(prev); next.set('reader_until', initialSnapshot); return next
    }, { replace: true })
  }, [params, setParams, initialSnapshot])

  useLayoutEffect(() => {
    if (directory.data && list.current) list.current.scrollTop = scrollPositions.get(listKey) || 0
  }, [listKey, readerOpen, directory.data])
  useLayoutEffect(() => {
    if (timeline.data && reader.current) reader.current.scrollTop = scrollPositions.get(positionKey) || 0
    if (focusTarget.current === 'heading' && readerOpen) {
      heading.current?.focus({ preventScroll: true }); focusTarget.current = null
    } else if (focusTarget.current === 'list' && !readerOpen) {
      list.current?.querySelector<HTMLElement>('[aria-pressed="true"]')?.focus({ preventScroll: true })
      focusTarget.current = null
    }
  }, [positionKey, readerOpen, timeline.data])

  function select(id: string) {
    focusTarget.current = 'heading'
    patch({ channel: id || null, reader_open: '1', reader_page: null, reader_until: until })
  }
  function paginate(next: number) {
    focusTarget.current = 'heading'
    scrollPositions.set(`${platform}:${channel}:${next}:${reading}`, 0)
    patch({ reader_page: String(next), reader_until: timeline.data?.until || until, reader_open: '1' })
  }
  const allTitle = platform === 'all' ? '전체 업데이트' : `${platforms[platform]} 전체`
  const allCount = (directory.data?.items || []).filter(item => platform === 'all' || item.platform === platform).reduce((sum, item) => sum + item.count, 0)
  function selectPlatform(value: string) {
    if (value === platform) return
    focusTarget.current = 'heading'
    scrollPositions.set(`${value}::1:${reading}`, 0)
    patch({ channel_type: value === 'all' ? null : value, channel: null, reader_page: null, reader_until: until })
  }
  const title = !channel ? allTitle : selected?.name || (directory.isLoading ? '소스 불러오는 중' : '선택한 소스')

  return <div className="channel-workspace" data-reader-open={readerOpen}>
    <aside className="channel-directory" aria-label="피드 소스 목록">
      <div className="shrink-0 space-y-2 border-b p-3">
        <div className="flex items-center justify-between gap-2"><h2 className="text-section font-semibold">내 피드</h2><Button asChild variant="ghost" size="sm"><Link to="/sources">소스 관리</Link></Button></div>
        <div className="relative"><Search aria-hidden="true" className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input aria-label="소스 검색" placeholder="채널, 기업, 인물 검색" value={query} onChange={event => patch({ channel_q: event.target.value || null }, true)} className="pl-9" /></div>
        <div className="channel-type-strip" role="group" aria-label="소스 종류" tabIndex={0}>
          {[['all', '전체'], ...Object.entries(platforms)].map(([value, label]) => <Button key={value} variant={platform === value ? 'secondary' : 'ghost'} size="sm" className="shrink-0 px-2 text-caption" aria-pressed={platform === value} onClick={() => selectPlatform(value)}>{label}</Button>)}
        </div>
      </div>
      <div ref={list} className="channel-list" tabIndex={0} aria-label="소스 목록 스크롤" onScroll={event => { if (directory.data) scrollPositions.set(listKey, event.currentTarget.scrollTop) }}>
        <Button variant="ghost" className="channel-entry" aria-pressed={!channel} onClick={() => select('')}>
          <span className="min-w-0 flex-1 text-left"><span className="block font-semibold">{allTitle}</span><span className="block text-caption text-muted-foreground">{platform === 'all' ? '팔로우한 소스와 Explorer' : platform === 'system' ? 'Explorer의 저장된 업데이트' : `팔로우한 ${platforms[platform]} 소스`}</span></span>
          {directory.data && <span className="channel-count" title="저장된 전체 게시물 수">{formatNumber(allCount)}</span>}
        </Button>
        {directory.isLoading && <div className="space-y-3 p-4" role="status" aria-label="소스 불러오는 중">{[1, 2, 3].map(i => <Skeleton key={i} className="h-16 w-full" />)}</div>}
        {directory.isError && <ErrorState message="소스 목록을 불러오지 못했습니다." onRetry={() => void directory.refetch()} />}
        {entries.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => select(item.id)} />)}
        {directory.data && entries.length === 0 && <EmptyState message={query || platform !== 'all' ? '조건에 맞는 소스가 없습니다.' : '팔로우한 소스가 아직 없습니다.'} />}
        <p className="px-4 py-5 text-caption text-muted-foreground">숫자는 저장된 게시물 수입니다.</p>
      </div>
    </aside>
    <section className="channel-reader" aria-labelledby="reader-title">
      <header className="reader-header">
        <Button variant="ghost" size="icon" className="reader-back shrink-0" aria-label="소스 목록으로" onClick={() => { focusTarget.current = 'list'; patch({ reader_open: '0' }) }}><ArrowLeft aria-hidden="true" /></Button>
        <div className="min-w-0 flex-1"><h2 id="reader-title" ref={heading} tabIndex={-1} className="truncate text-section font-semibold outline-offset-4">{title}</h2><p className="text-caption text-muted-foreground">{selected ? `${channelLabel(selected)} · 저장 ${formatNumber(selected.count)}건 · ` : ''}최신순</p></div>
        <div className="reader-actions">{platform !== 'system' && selected?.platform !== 'system' && <SegmentTabs tabs={[{ value: 'original', label: '원문' }, { value: 'summary', label: '요약' }]} value={reading} onChange={value => patch({ reading: value })} />}
          <Button variant="ghost" size="icon" aria-label="피드 새로고침" disabled={timeline.isFetching || directory.isFetching} onClick={() => { scrollPositions.set(`${platform}:${channel}:1:${reading}`, 0); patch({ reader_until: new Date().toISOString(), reader_page: null }) }}><RefreshCw aria-hidden="true" className={timeline.isFetching ? 'animate-spin' : ''} /></Button></div>
      </header>
      <div ref={reader} className="reader-scroll" tabIndex={0} aria-label="게시물 스크롤" onScroll={event => { if (timeline.data) scrollPositions.set(positionKey, event.currentTarget.scrollTop) }}>
        <div className="reader-articles" aria-busy={timeline.isFetching}>
          <p className="pb-2 text-caption text-muted-foreground">{(platform === 'system' || selected?.platform === 'system') ? 'Explorer가 저장한 요약과 수집 업데이트입니다.' : '내가 읽는 사람들의 생각과 쌓이는 시장 정보'}</p>
          {timeline.isLoading && <div role="status" aria-label="게시물 불러오는 중" className="space-y-4">{[1, 2, 3].map(i => <Skeleton key={i} className="h-48 w-full" />)}</div>}
          {timeline.isError && <ErrorState message={timeline.data ? '갱신에 실패했습니다. 이전 자료를 표시합니다.' : '게시물을 불러오지 못했습니다.'} onRetry={() => void timeline.refetch()} />}
          {timeline.data?.items.map(item => item.document ? <DocumentCard key={item.id} doc={item.document} variant="row" timeLabel={item.time_label} reading={reading} onChipFilter={tag => navigate(`/feed?view=documents&q=${encodeURIComponent(tag.name)}`)} /> : <SystemPost key={item.id} item={item} variant="row" presentation="reading" />)}
          {timeline.data?.items.length === 0 && <EmptyState message={channel ? '이 소스에 저장된 게시물이 없습니다.' : '아직 저장된 업데이트가 없습니다.'} />}
          {timeline.data && <nav className="flex flex-wrap items-center justify-between gap-3 border-t pt-5" aria-label="게시물 페이지">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => paginate(page - 1)}><ChevronLeft aria-hidden="true" />이전</Button>
            <span className="text-caption text-muted-foreground" role="status">{page}페이지{!timeline.data.has_more && ' · 마지막'}</span>
            <Button variant="outline" size="sm" disabled={!timeline.data.has_more || page >= 100} onClick={() => paginate(page + 1)}>다음<ChevronRight aria-hidden="true" /></Button>
            {page >= 100 && timeline.data.has_more && <p className="w-full text-caption text-muted-foreground">더 이전 자료는 <Link to="/feed?view=documents" className="underline">문서 검색</Link>에서 확인하세요.</p>}
          </nav>}
        </div>
      </div>
    </section>
  </div>
}

function ChannelEntry({ item, selected, onSelect }: { item: TimelineChannel; selected: boolean; onSelect: () => void }) {
  const snippet = item.preview.replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim()
  return <Button variant="ghost" className="channel-entry" aria-pressed={selected} onClick={onSelect}>
    <span className="min-w-0 flex-1 text-left">
      <span className="flex items-baseline gap-2"><span className="min-w-0 flex-1 truncate font-semibold">{item.name}</span>{item.latest_at && <time className="shrink-0 text-caption text-muted-foreground" dateTime={item.latest_at} title={item.latest_at}>{formatRelativeTime(item.latest_at)}</time>}</span>
      <span className="mt-0.5 block text-caption text-muted-foreground">{channelLabel(item)}</span>
      <span className="mt-1 flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-sm font-normal text-muted-foreground">{snippet || '아직 저장된 게시물이 없습니다'}</span><span className="channel-count" title="저장된 게시물 수">{formatNumber(item.count)}</span></span>
    </span>
  </Button>
}
