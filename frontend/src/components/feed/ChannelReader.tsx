import { forwardRef, useEffect, useLayoutEffect, useRef, useState, type ComponentProps } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ArrowLeft, ChevronDown, ChevronLeft, ChevronRight, RefreshCw, Search, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import { DocumentCard, SystemPost } from '@/components/feed/FeedPost'
import { useMarkAllRead, useMarkChannelRead, useTimeline, useTimelineChannels } from '@/hooks/useTimeline'
import { useFeedTopics } from '@/hooks/useFeedTopics'
import { useMarketToday } from '@/hooks/useMarketToday'
import { FEED_PLATFORMS, feedPlatform, isQuiet, type FeedPlatform } from '@/lib/feed'
import { SYSTEM_KIND_LABEL, groupDirectory, systemKind, type DirectoryGroup } from '@/lib/canvas'
import { sessionMemory } from '@/lib/sessionMemory'
import { cn } from '@/lib/utils'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import type { TimelineChannel } from '@/types'
import { track } from '@/lib/usage'

/** 왼쪽 종류 칩 — Explorer(system)는 칩 없이 목록 맨 아래 묶음으로 */
const TYPE_CHIPS = [['all', '전체'], ...Object.entries(FEED_PLATFORMS).filter(([k]) => k !== 'system')] as [FeedPlatform, string][]
const isSystemChannel = (id: string) => !!id && Object.hasOwn(SYSTEM_KIND_LABEL, systemKind(id))
function channelLabel(item: TimelineChannel) {
  const kind = SYSTEM_KIND_LABEL[systemKind(item.id)]
  return item.platform === 'system' && kind ? `Explorer · ${kind}` : FEED_PLATFORMS[item.platform]
}
// 화면 위치만 기억한다. 읽음 표시는 channel_reads(D-200)에 있고 문서 코퍼스에는 쓰지 않는다
const scrollPositions = sessionMemory<number>('explorer.reader.positions')

/**
 * 피드 리더(D-325 — 4a 3칸 피드를 번복하고 옛 ChannelReader 구성으로 되돌림, ia-redesign §4.5 '11-06 번복').
 * 왼쪽 '내 피드'(검색 · 종류 칩 · 소스 줄, Explorer 산출물은 맨 아래 접힌 묶음) | 오른쪽 선택한 소스의 글(머리 · 주제 칩 띠 · 글 카드 · 페이지).
 * 넓은 화면은 두 칸이 화면 높이 안에서 각자 스크롤한다(§4.34). 폰은 소스 목록 ↔ 글 화면을 오간다(reader_open).
 * URL이 상태: channel_type · channel · channel_q · reader_topic · reader_page · reader_until · reader_open.
 */
export function ChannelReader() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [initialSnapshot] = useState(() => new Date().toISOString())
  const until = params.get('reader_until') || initialSnapshot
  const channel = params.get('channel') || ''
  const page = Math.max(1, Math.min(100, Math.floor(Number(params.get('reader_page'))) || 1))
  const query = params.get('channel_q') || ''
  const topic = params.get('reader_topic') || ''   // 주제 칩 (D-208)
  const platform = feedPlatform(params.toString())
  const readerOpen = params.get('reader_open') === '1' || (!params.has('reader_open') && !!channel)
  const systemView = platform === 'system' || isSystemChannel(channel)
  const directory = useTimelineChannels(until)
  const timeline = useTimeline({ scope: systemView ? 'system' : 'sources', kind: 'all', source: systemView ? 'all' : platform, channel: channel || undefined, topic: topic || undefined, page, until })
  const channels = directory.data?.items ?? []
  const selected = channels.find(item => item.id === channel)
  const markRead = useMarkChannelRead()
  const markAll = useMarkAllRead()
  const entries = channels.filter(item =>
    (platform === 'all' || item.platform === platform) &&
    `${item.name} ${item.id}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const heading = useRef<HTMLHeadingElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const reader = useRef<HTMLDivElement>(null)
  const focusTarget = useRef<'heading' | 'list' | null>(null)
  const positionKey = `${platform}:${channel}:${topic}:${page}`
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

  // 소스를 열어 게시물이 화면에 오면 최신 시각까지 읽음으로 표시한다 (D-200). 주제로 거른 화면은 일부만 보이므로 표시하지 않는다 (D-208)
  useEffect(() => {
    if (topic || !channel || !selected || selected.unread <= 0 || !selected.latest_at || !timeline.data || markRead.isPending) return
    markRead.mutate({ channel, read_until: selected.latest_at })
  }, [topic, channel, selected, timeline.data, markRead])

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
    if (id) track('action', 'feed.source', { entity: id })
    patch({ channel: id || null, reading: null, reader_topic: null, reader_open: '1', reader_page: null, reader_until: until })
  }
  function paginate(next: number) {
    focusTarget.current = 'heading'
    scrollPositions.set(`${platform}:${channel}:${topic}:${next}`, 0)
    patch({ reader_page: String(next), reader_until: timeline.data?.until || until, reader_open: '1' })
  }
  function selectPlatform(value: FeedPlatform) {
    if (value === platform) return
    focusTarget.current = 'heading'
    patch({ channel_type: value === 'all' ? null : value, channel: null, reading: null, reader_topic: null, reader_page: null, reader_until: until })
  }
  const allTitle = platform === 'all' ? '팔로우한 소스 전체' : `${FEED_PLATFORMS[platform]} 전체`
  // '전체' = 사람 소스만(D-301). Explorer 산출물은 목록 맨 아래 묶음과 상단 바 'AI가 최근 만든 것'에서 본다
  const allUnread = channels.filter(item => platform === 'all' ? item.platform !== 'system' : item.platform === platform).reduce((sum, item) => sum + item.unread, 0)
  // 검색어가 없으면 사람 소스를 먼저, 시스템 항목은 접힌 Explorer 묶음으로
  const grouped = !query.trim() && (platform === 'all' || platform === 'system') ? groupDirectory(entries) : null
  const title = !channel ? allTitle : selected?.name || (directory.isLoading ? '소스 불러오는 중' : '선택한 소스')
  // '모두 읽음'(D-301) = 지금 종류 칩 범위. 소스를 고르면 그 소스는 열 때 읽음 처리되므로 두지 않는다
  const markScope = !channel && !topic && platform !== 'system' ? platform : null

  return <div className="grid min-h-0 border bg-card md:flex-1 md:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)]">
    <aside aria-label="피드 소스 목록" className={cn('flex min-h-0 min-w-0 flex-col md:border-r', readerOpen && 'max-md:hidden')}>
      <div className="flex-none space-y-2 border-b p-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-section font-semibold">내 피드</h2>
          <Button asChild variant="ghost" size="sm" className="text-ink-2"><Link to="/admin/sources">소스 관리</Link></Button>
        </div>
        <div className="relative">
          <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" />
          <Input aria-label="소스 검색" placeholder="채널, 기업, 인물 검색" value={query} onChange={event => patch({ channel_q: event.target.value || null }, true)} className="pl-9" />
        </div>
        <div role="group" aria-label="소스 종류" className="flex min-w-0 flex-wrap gap-1">
          {TYPE_CHIPS.map(([value, label]) => <Button key={value} variant={platform === value ? 'secondary' : 'ghost'} size="sm" aria-pressed={platform === value}
            className={cn('shrink-0 px-2 text-caption', platform === value ? 'text-ink' : 'text-ink-2')} onClick={() => selectPlatform(value)}>{label}</Button>)}
        </div>
      </div>
      <div ref={list} tabIndex={0} aria-label="소스 목록 스크롤" className="min-h-0 flex-1 p-2 md:overflow-y-auto md:overscroll-y-contain"
        onScroll={event => { if (directory.data) scrollPositions.set(listKey, event.currentTarget.scrollTop) }}>
        <EntryButton selected={!channel} onClick={() => select('')}>
          <span className="min-w-0 flex-1 text-left">
            <span className="block font-semibold">{allTitle}</span>
            <span className="block text-caption text-ink-3">{platform === 'all' ? '텔레그램·블로그·유튜브·투자자 메모' : platform === 'system' ? 'Explorer의 저장된 업데이트' : `팔로우한 ${FEED_PLATFORMS[platform]} 소스`}</span>
          </span>
          {directory.data && allUnread > 0 && <UnreadCount n={allUnread} />}
        </EntryButton>
        {directory.isLoading && <div className="space-y-2 p-2" role="status" aria-label="소스 불러오는 중">{[1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-[72px] w-full" />)}</div>}
        {directory.isError && <ErrorState message="소스 목록을 불러오지 못했습니다." onRetry={() => void directory.refetch()} />}
        {grouped ? <>
          {grouped.human.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => select(item.id)} />)}
          {grouped.explorer.count > 0 && <ExplorerGroup key={platform} explorer={grouped.explorer} channel={channel} defaultOpen={platform === 'system' || isSystemChannel(channel)}
            onSelect={select} onSelectAll={platform === 'all' ? () => selectPlatform('system') : undefined} />}
        </> : entries.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => select(item.id)} />)}
        {directory.data && entries.length === 0 && <EmptyState message={query || platform !== 'all' ? '조건에 맞는 소스가 없습니다.' : '팔로우한 소스가 아직 없습니다.'} />}
      </div>
    </aside>

    <section aria-labelledby="reader-title" className={cn('flex min-h-0 min-w-0 flex-col', !readerOpen && 'max-md:hidden')}>
      <header className="flex flex-none flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
        <Button variant="ghost" size="icon" className="shrink-0 md:hidden" aria-label="소스 목록으로" onClick={() => { focusTarget.current = 'list'; patch({ reader_open: '0' }) }}><ArrowLeft aria-hidden="true" /></Button>
        <div className="min-w-0 flex-1">
          <h2 id="reader-title" ref={heading} tabIndex={-1} className="truncate text-section font-semibold outline-offset-4">{title}</h2>
          <p className="flex flex-wrap items-center gap-x-1 text-caption text-ink-3">
            <span>{selected ? `${channelLabel(selected)} · 저장 ${formatNumber(selected.count)}건${selected.unread > 0 ? ` · 안 읽음 ${formatNumber(selected.unread)}건` : ''} · ` : ''}최신순</span>
            {markScope && directory.data && allUnread > 0 && <>
              <span aria-hidden>·</span>
              <Button variant="link" size="xs" className="h-auto px-0 text-caption text-ink-2" disabled={markAll.isPending}
                onClick={() => { track('action', 'feed.mark_all_read', { entity: markScope }); markAll.mutate({ platform: markScope, read_until: until }, { onError: e => toast.error(e instanceof Error ? e.message : '읽음으로 바꾸지 못했습니다.') }) }}>모두 읽음</Button>
            </>}
          </p>
        </div>
        <div className="flex items-center gap-2 max-sm:w-full max-sm:justify-between">
          <Button variant="ghost" size="icon" aria-label="피드 새로고침" disabled={timeline.isFetching || directory.isFetching}
            onClick={() => { scrollPositions.set(`${platform}:${channel}:${topic}:1`, 0); patch({ reader_until: new Date().toISOString(), reader_page: null }) }}>
            <RefreshCw aria-hidden="true" className={timeline.isFetching ? 'animate-spin' : ''} />
          </Button>
        </div>
      </header>
      <TopicStrip active={topic} onPick={value => { focusTarget.current = 'heading'; patch({ reader_topic: value, reader_page: null }) }} />
      <div ref={reader} tabIndex={0} aria-label="게시물 스크롤" className="min-h-0 flex-1 md:overflow-y-auto md:overscroll-y-contain"
        onScroll={event => { if (timeline.data) scrollPositions.set(positionKey, event.currentTarget.scrollTop) }}>
        <div className="mx-auto max-w-[860px] px-6 pt-2 pb-6 max-md:px-4" aria-busy={timeline.isFetching}>
          {timeline.isLoading && <div role="status" aria-label="게시물 불러오는 중" className="space-y-4 pt-4">{[1, 2, 3].map(i => <Skeleton key={i} className="h-48 w-full" />)}</div>}
          {timeline.isError && <ErrorState message={timeline.data ? '갱신에 실패했습니다. 이전 자료를 표시합니다.' : '게시물을 불러오지 못했습니다.'} onRetry={() => void timeline.refetch()} />}
          {timeline.data?.items.map(item => item.document
            ? <DocumentCard key={item.id} doc={item.document} timeLabel={item.time_label} onChipFilter={tag => navigate(`/feed?view=documents&q=${encodeURIComponent(tag.name)}`)} />
            : <SystemPost key={item.id} item={item} variant="row" presentation="reading" />)}
          {timeline.data?.items.length === 0 && <EmptyState message={topic ? `‘${topic}’ 주제의 게시물이 없습니다.` : channel ? '이 소스에 저장된 게시물이 없습니다.' : '아직 저장된 업데이트가 없습니다.'} />}
          {timeline.data && <nav className="flex flex-wrap items-center justify-between gap-3 border-t pt-5" aria-label="게시물 페이지">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => paginate(page - 1)}><ChevronLeft aria-hidden="true" />이전</Button>
            <span className="text-caption text-ink-3" role="status">{page}페이지{!timeline.data.has_more && ' · 마지막'}</span>
            <Button variant="outline" size="sm" disabled={!timeline.data.has_more || page >= 100} onClick={() => paginate(page + 1)}>다음<ChevronRight aria-hidden="true" /></Button>
            {page >= 100 && timeline.data.has_more && <p className="w-full text-caption text-ink-3">더 이전 자료는 <Link to="/feed?view=documents" className="underline">문서 검색</Link>에서 확인하세요.</p>}
          </nav>}
        </div>
      </div>
    </section>
  </div>
}

/**
 * 글 칸 위쪽 띠 — 주목 주제 · 부상 종목 칩(누르면 그 주제로 거름, D-208)과 Market Today 최신 회차 한 줄.
 * 4a의 세 번째 칸(부상 종목 + Market Today)을 여기로 올렸다(D-325). 칩 줄은 가로 스크롤이라 띠 높이가 늘지 않는다
 */
function TopicStrip({ active, onPick }: { active: string; onPick: (topic: string | null) => void }) {
  const { themes, stocks } = useFeedTopics()
  const groups = [{ label: '주목 주제', names: themes }, { label: '부상 종목', names: stocks }].filter(g => g.names.length > 0)
  return <div className="flex flex-none flex-wrap items-start gap-x-4 gap-y-1.5 border-b px-4 py-2.5">
    <div className="min-w-0 flex-1 space-y-1.5 max-md:basis-full">
      {active ? <div className="flex items-center gap-2">
        <span className="w-14 shrink-0 text-caption text-ink-3">주제</span>
        <Button variant="secondary" size="xs" onClick={() => onPick(null)} aria-label={`주제 ${active} 해제`}>{active}<X aria-hidden="true" /></Button>
      </div> : groups.map(g => <div key={g.label} className="flex min-w-0 items-center gap-1.5 overflow-x-auto overscroll-x-contain [scrollbar-width:none]">
        <span className="w-14 shrink-0 text-caption text-ink-3">{g.label}</span>
        {g.names.map(name => <Button key={name} variant="outline" size="xs" className="shrink-0 font-normal" onClick={() => onPick(name)}>{name}</Button>)}
      </div>)}
    </div>
    <MarketTodayLink />
  </div>
}

/** 'Market Today 16:00 정리 ›' — 오늘 최신 회차. 회차가 없거나 못 불러오면 이름만 */
function MarketTodayLink() {
  const { data } = useMarketToday()
  const label = data?.current?.label.replace(" 마감", "")
  return <Link to="/home" className="flex h-6 shrink-0 items-center gap-0.5 text-[13px] font-medium text-ink hover:opacity-75">
    Market Today{label && <span className="font-mono text-xs font-normal text-ink-2"> {label} 정리</span>}<ChevronRight aria-hidden="true" className="size-3.5" />
  </Link>
}

/** 소스 목록 한 줄 — Collapsible 트리거로도 쓰므로 ref·속성을 그대로 넘긴다 */
const EntryButton = forwardRef<HTMLButtonElement, ComponentProps<typeof Button> & { selected?: boolean }>(function EntryButton({ selected, className, ...rest }, ref) {
  return <Button ref={ref} variant="ghost" aria-pressed={selected} {...rest}
    className={cn('h-auto min-h-[60px] w-full justify-start gap-2.5 rounded-lg p-2.5 font-normal whitespace-normal hover:bg-chip aria-pressed:bg-chip', className)} />
})

function UnreadCount({ n, title }: { n: number; title?: string }) {
  return <span title={title ?? '안 읽은 게시물 수'} className="shrink-0 rounded-full bg-action px-1.5 py-0.5 font-mono text-[11px] leading-none font-semibold text-action-ink tabular-nums">{formatNumber(n)}</span>
}

/** Explorer 묶음 — 시스템 소스(기업 요약·컨콜·인물 …)를 접어 사람 소스가 먼저 보이게 (canvas.md §1). 열림은 화면 편의라 URL에 두지 않는다 */
function ExplorerGroup({ explorer, channel, defaultOpen, onSelect, onSelectAll }: {
  explorer: ReturnType<typeof groupDirectory>['explorer']; channel: string; defaultOpen: boolean
  onSelect: (id: string) => void; onSelectAll?: () => void
}) {
  return <Collapsible defaultOpen={defaultOpen} className="mt-1 border-t pt-1">
    <CollapsibleTrigger asChild>
      <EntryButton className="group/explorer">
        <Sparkles aria-hidden="true" className="size-4 shrink-0 text-hyp" />
        <span className="min-w-0 flex-1 text-left"><span className="block font-semibold">Explorer</span><span className="block text-caption text-ink-3">시스템이 만든 요약·컨콜 {formatNumber(explorer.count)}개</span></span>
        {explorer.unread > 0 && <UnreadCount n={explorer.unread} />}
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-ink-3 transition-transform group-data-[state=open]/explorer:rotate-180" />
      </EntryButton>
    </CollapsibleTrigger>
    <CollapsibleContent className="pl-3">
      {onSelectAll && <EntryButton onClick={onSelectAll} className="min-h-10"><span className="min-w-0 flex-1 text-left text-sm">Explorer 업데이트 전체 보기</span></EntryButton>}
      {explorer.singles.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => onSelect(item.id)} />)}
      {explorer.groups.map(g => <KindGroup key={g.kind} group={g} channel={channel} onSelect={onSelect} />)}
    </CollapsibleContent>
  </Collapsible>
}

function KindGroup({ group, channel, onSelect }: { group: DirectoryGroup; channel: string; onSelect: (id: string) => void }) {
  return <Collapsible defaultOpen={group.items.some(i => i.id === channel)}>
    <CollapsibleTrigger asChild>
      <EntryButton className="group/kind">
        <span className="min-w-0 flex-1 text-left"><span className="block text-sm font-medium">{group.label}</span><span className="block text-caption text-ink-3">{formatNumber(group.items.length)}개 소스</span></span>
        {group.unread > 0 && <UnreadCount n={group.unread} />}
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-ink-3 transition-transform group-data-[state=open]/kind:rotate-180" />
      </EntryButton>
    </CollapsibleTrigger>
    <CollapsibleContent>
      {group.items.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => onSelect(item.id)} />)}
    </CollapsibleContent>
  </Collapsible>
}

/** 소스 줄 — 이름 · 시각 / 종류 / 최근 글 제목 · 안 읽음 수. 7일 넘게 새 글이 없으면 흐리게(§4.28) */
function ChannelEntry({ item, selected, onSelect }: { item: TimelineChannel; selected: boolean; onSelect: () => void }) {
  const snippet = item.preview.replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim()
  const quiet = item.platform !== 'system' && isQuiet(item.latest_at)
  return <EntryButton selected={selected} onClick={onSelect} className={cn('min-h-[72px]', quiet && !selected && 'opacity-60')}>
    <span className="min-w-0 flex-1 text-left">
      <span className="flex items-baseline gap-2"><span className="min-w-0 flex-1 truncate font-semibold">{item.name}</span>{item.latest_at && <time className="shrink-0 text-caption text-ink-3" dateTime={item.latest_at} title={item.latest_at}>{formatRelativeTime(item.latest_at)}</time>}</span>
      <span className="mt-0.5 block text-caption text-ink-3">{channelLabel(item)}</span>
      <span className="mt-1 flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-sm text-ink-2">{snippet || '아직 저장된 게시물이 없습니다'}</span>{item.unread > 0 && <UnreadCount n={item.unread} title={`안 읽은 게시물 ${formatNumber(item.unread)} · 저장 ${formatNumber(item.count)}`} />}</span>
    </span>
  </EntryButton>
}
