import { sessionMemory } from "@/lib/sessionMemory"
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ChevronDown, ChevronLeft, ChevronRight, FileSearch, RefreshCw, Search, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { DocumentCard, SystemPost } from './FeedPost'
import { useMarkChannelRead, useTimeline, useTimelineChannels } from '@/hooks/useTimeline'
import { useFeedTopics } from '@/hooks/useFeedTopics'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import { SYSTEM_KIND_LABEL, groupDirectory, isSystemChannel, systemKind, type DirectoryGroup } from '@/lib/canvas'
import type { TimelineChannel } from '@/types'

const platforms = { telegram: '텔레그램', blog: '블로그', youtube: '유튜브', system: 'Explorer' }
function channelLabel(item: TimelineChannel) {
  const kind = SYSTEM_KIND_LABEL[systemKind(item.id)]
  return item.platform === 'system' && kind ? `Explorer · ${kind}` : platforms[item.platform]
}
// UI-only positions. Read marks live in channel_reads (D-200), never in the document corpus.
const scrollPositions = sessionMemory<number>('explorer.reader.positions')

export function ChannelReader() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [initialSnapshot] = useState(() => new Date().toISOString())
  const until = params.get('reader_until') || initialSnapshot
  const channel = params.get('channel') || ''
  const page = Math.max(1, Math.min(100, Math.floor(Number(params.get('reader_page'))) || 1))
  const query = params.get('channel_q') || ''
  const topic = params.get('reader_topic') || ''   // 주제 칩 (D-208)
  const requestedPlatform = params.get('channel_type') || 'all'
  const platform = Object.hasOwn(platforms, requestedPlatform) ? requestedPlatform as keyof typeof platforms : 'all'
  // 블로그·유튜브는 원문이 길어 요약을 기본으로 연다. 소스 ID 접두사(`youtube:…`)로 판단해 목록 로딩 전에도 같다.
  // URL의 명시적 `reading`이 항상 우선한다.
  const contextPlatform = channel ? channel.split(':')[0] : platform
  const requestedReading = params.get('reading')
  const reading = requestedReading === 'summary' || requestedReading === 'original' ? requestedReading
    : contextPlatform === 'blog' || contextPlatform === 'youtube' ? 'summary' : 'original'
  const readerOpen = params.get('reader_open') === '1' || (!params.has('reader_open') && !!channel)
  const directory = useTimelineChannels(until)
  const timeline = useTimeline({ scope: platform === 'system' ? 'system' : 'sources', kind: 'all', source: platform === 'system' ? 'all' : platform, channel: channel || undefined, topic: topic || undefined, page, until })
  const selected = directory.data?.items.find(item => item.id === channel)
  const markRead = useMarkChannelRead()
  const entries = (directory.data?.items || []).filter(item =>
    (platform === 'all' || item.platform === platform) &&
    `${item.name} ${item.id}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const heading = useRef<HTMLHeadingElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const reader = useRef<HTMLDivElement>(null)
  const focusTarget = useRef<'heading' | 'list' | null>(null)
  const positionKey = `${platform}:${channel}:${topic}:${page}:${reading}`
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

  // 소스를 열어 게시물이 화면에 오면 최신 시각까지 읽음으로 표시한다 (D-200). 목록 배지가 0이 되고 새 글이 오면 다시 센다.
  useEffect(() => {
    // 주제로 거른 화면은 일부만 보이므로 소스 전체를 읽음으로 표시하지 않는다 (D-208)
    if (topic || !channel || !selected || selected.unread <= 0 || !selected.latest_at || !timeline.data || markRead.isPending) return
    markRead.mutate({ channel, read_until: selected.latest_at })
  }, [channel, selected, timeline.data, markRead])

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
    patch({ channel: id || null, reading: null, reader_topic: null, reader_open: '1', reader_page: null, reader_until: until })
  }
  function paginate(next: number) {
    focusTarget.current = 'heading'
    scrollPositions.set(`${platform}:${channel}:${next}:${reading}`, 0)
    patch({ reader_page: String(next), reader_until: timeline.data?.until || until, reader_open: '1' })
  }
  const allTitle = platform === 'all' ? '팔로우한 소스 전체' : `${platforms[platform]} 전체`
  // 전체 = 사람 소스만. Explorer 생성물은 디렉터리의 Explorer 묶음과 'AI가 최근 만든 것'에서 본다 (canvas.md §1)
  const allUnread = (directory.data?.items || []).filter(item => platform === 'all' ? item.platform !== 'system' : item.platform === platform).reduce((sum, item) => sum + item.unread, 0)
  // 검색어가 없으면 사람 소스를 먼저, 시스템 항목은 접힌 Explorer 묶음으로
  const grouped = !query.trim() && (platform === 'all' || platform === 'system') ? groupDirectory(entries) : null
  function selectPlatform(value: string) {
    if (value === platform) return
    focusTarget.current = 'heading'
    scrollPositions.set(`${value}::1:${reading}`, 0)
    patch({ channel_type: value === 'all' ? null : value, channel: null, reading: null, reader_topic: null, reader_page: null, reader_until: until })
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
          <span className="min-w-0 flex-1 text-left"><span className="block font-semibold">{allTitle}</span><span className="block text-caption text-muted-foreground">{platform === 'all' ? '텔레그램·블로그·유튜브' : platform === 'system' ? 'Explorer의 저장된 업데이트' : `팔로우한 ${platforms[platform]} 소스`}</span></span>
          {directory.data && allUnread > 0 && <span className="channel-count channel-count-unread" title="안 읽은 게시물 수">{formatNumber(allUnread)}</span>}
        </Button>
        {directory.isLoading && <div className="space-y-3 p-4" role="status" aria-label="소스 불러오는 중">{[1, 2, 3].map(i => <Skeleton key={i} className="h-16 w-full" />)}</div>}
        {directory.isError && <ErrorState message="소스 목록을 불러오지 못했습니다." onRetry={() => void directory.refetch()} />}
        {grouped ? <>
          {grouped.human.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => select(item.id)} />)}
          {grouped.explorer.count > 0 && <ExplorerGroup key={platform} explorer={grouped.explorer} channel={channel} defaultOpen={platform === 'system' || isSystemChannel(channel)}
            onSelect={select} onSelectAll={platform === 'all' ? () => selectPlatform('system') : undefined} />}
        </> : entries.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => select(item.id)} />)}
        {directory.data && entries.length === 0 && <EmptyState message={query || platform !== 'all' ? '조건에 맞는 소스가 없습니다.' : '팔로우한 소스가 아직 없습니다.'} />}
        <p className="px-4 py-5 text-caption text-muted-foreground">숫자는 아직 읽지 않은 게시물 수입니다. 소스를 열면 그때까지의 게시물이 읽음으로 표시됩니다.</p>
      </div>
    </aside>
    <section className="channel-reader" aria-labelledby="reader-title">
      <header className="reader-header">
        <Button variant="ghost" size="icon" className="reader-back shrink-0" aria-label="소스 목록으로" onClick={() => { focusTarget.current = 'list'; patch({ reader_open: '0' }) }}><ArrowLeft aria-hidden="true" /></Button>
        <div className="min-w-0 flex-1"><h2 id="reader-title" ref={heading} tabIndex={-1} className="truncate text-section font-semibold outline-offset-4">{title}</h2><p className="text-caption text-muted-foreground">{selected ? `${channelLabel(selected)} · 저장 ${formatNumber(selected.count)}건${selected.unread > 0 ? ` · 안 읽음 ${formatNumber(selected.unread)}건` : ''} · ` : ''}최신순</p></div>
        <div className="reader-actions"><Button asChild variant="ghost" size="sm"><Link to="/feed?view=documents"><FileSearch aria-hidden="true" />문서 검색</Link></Button>{platform !== 'system' && selected?.platform !== 'system' && <SegmentTabs tabs={[{ value: 'original', label: '원문' }, { value: 'summary', label: '요약' }]} value={reading} onChange={value => patch({ reading: value })} />}
          <Button variant="ghost" size="icon" aria-label="피드 새로고침" disabled={timeline.isFetching || directory.isFetching} onClick={() => { scrollPositions.set(`${platform}:${channel}:1:${reading}`, 0); patch({ reader_until: new Date().toISOString(), reader_page: null }) }}><RefreshCw aria-hidden="true" className={timeline.isFetching ? 'animate-spin' : ''} /></Button></div>
      </header>
      <div ref={reader} className="reader-scroll" tabIndex={0} aria-label="게시물 스크롤" onScroll={event => { if (timeline.data) scrollPositions.set(positionKey, event.currentTarget.scrollTop) }}>
        <div className="reader-articles" aria-busy={timeline.isFetching}>
          <p className="pb-2 text-caption text-muted-foreground">{(platform === 'system' || selected?.platform === 'system') ? 'Explorer가 저장한 요약과 수집 업데이트입니다.' : '내가 읽는 사람들의 생각과 쌓이는 시장 정보'}</p>
          <TopicChips active={topic} onPick={value => { focusTarget.current = 'heading'; patch({ reader_topic: value, reader_page: null }) }} />
          {timeline.isLoading && <div role="status" aria-label="게시물 불러오는 중" className="space-y-4">{[1, 2, 3].map(i => <Skeleton key={i} className="h-48 w-full" />)}</div>}
          {timeline.isError && <ErrorState message={timeline.data ? '갱신에 실패했습니다. 이전 자료를 표시합니다.' : '게시물을 불러오지 못했습니다.'} onRetry={() => void timeline.refetch()} />}
          {timeline.data?.items.map(item => item.document ? <DocumentCard key={item.id} doc={item.document} variant="row" timeLabel={item.time_label} reading={reading} onChipFilter={tag => navigate(`/feed?view=documents&q=${encodeURIComponent(tag.name)}`)} /> : <SystemPost key={item.id} item={item} variant="row" presentation="reading" />)}
          {timeline.data?.items.length === 0 && <EmptyState message={topic ? `‘${topic}’ 주제의 게시물이 없습니다.` : channel ? '이 소스에 저장된 게시물이 없습니다.' : '아직 저장된 업데이트가 없습니다.'} />}
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

/** 피드 상단 주제 칩 (D-208) — 시장 탭에서 옮겨 온 주목 주제·부상 종목. 누르면 그 주제로 피드를 거른다. */
function TopicChips({ active, onPick }: { active: string; onPick: (topic: string | null) => void }) {
  const { themes, stocks } = useFeedTopics()
  if (active) return <div className="flex items-center gap-2 pb-3">
    <span className="text-caption text-muted-foreground">주제</span>
    <Button variant="secondary" size="sm" className="h-7 gap-1 px-2.5 text-caption" onClick={() => onPick(null)} aria-label={`주제 ${active} 해제`}>{active}<X aria-hidden="true" className="size-3" /></Button>
  </div>
  const groups = [{ label: '주목 주제', names: themes }, { label: '부상 종목', names: stocks }].filter(g => g.names.length > 0)
  if (groups.length === 0) return null   // 로딩·오류·빈 신호 모두 칩 줄을 생략한다(피드 본문과 독립)
  return <div className="space-y-1.5 pb-3">
    {groups.map(g => <div key={g.label} className="flex flex-wrap items-center gap-1.5">
      <span className="w-14 shrink-0 text-caption text-muted-foreground">{g.label}</span>
      {g.names.map(name => <Button key={name} variant="outline" size="sm" className="h-7 px-2.5 text-caption font-normal" onClick={() => onPick(name)}>{name}</Button>)}
    </div>)}
  </div>
}

/** Explorer 묶음 — 시스템 소스(기업 요약·컨콜·인물 …)를 접어 사람 소스가 먼저 보이게 (canvas.md §1). 열림은 화면 편의라 URL에 두지 않는다 */
function ExplorerGroup({ explorer, channel, defaultOpen, onSelect, onSelectAll }: {
  explorer: ReturnType<typeof groupDirectory>['explorer']; channel: string; defaultOpen: boolean
  onSelect: (id: string) => void; onSelectAll?: () => void
}) {
  return <Collapsible defaultOpen={defaultOpen} className="border-t">
    <CollapsibleTrigger asChild>
      <Button variant="ghost" className="channel-entry group/explorer">
        <Sparkles aria-hidden="true" className="size-4 shrink-0 text-hypothesis" />
        <span className="min-w-0 flex-1 text-left"><span className="block font-semibold">Explorer</span><span className="block text-caption text-muted-foreground">시스템이 만든 요약·컨콜 {formatNumber(explorer.count)}개</span></span>
        {explorer.unread > 0 && <span className="channel-count channel-count-unread" title="안 읽은 게시물 수">{formatNumber(explorer.unread)}</span>}
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/explorer:rotate-180" />
      </Button>
    </CollapsibleTrigger>
    <CollapsibleContent className="pl-3">
      {onSelectAll && <Button variant="ghost" className="channel-entry" onClick={onSelectAll}><span className="min-w-0 flex-1 text-left text-sm">Explorer 업데이트 전체 보기</span></Button>}
      {explorer.singles.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => onSelect(item.id)} />)}
      {explorer.groups.map(g => <KindGroup key={g.kind} group={g} channel={channel} onSelect={onSelect} />)}
    </CollapsibleContent>
  </Collapsible>
}

function KindGroup({ group, channel, onSelect }: { group: DirectoryGroup; channel: string; onSelect: (id: string) => void }) {
  return <Collapsible defaultOpen={group.items.some(i => i.id === channel)}>
    <CollapsibleTrigger asChild>
      <Button variant="ghost" className="channel-entry group/kind">
        <span className="min-w-0 flex-1 text-left"><span className="block text-sm font-medium">{group.label}</span><span className="block text-caption text-muted-foreground">{formatNumber(group.items.length)}개 소스</span></span>
        {group.unread > 0 && <span className="channel-count channel-count-unread" title="안 읽은 게시물 수">{formatNumber(group.unread)}</span>}
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/kind:rotate-180" />
      </Button>
    </CollapsibleTrigger>
    <CollapsibleContent>
      {group.items.map(item => <ChannelEntry key={item.id} item={item} selected={channel === item.id} onSelect={() => onSelect(item.id)} />)}
    </CollapsibleContent>
  </Collapsible>
}

function ChannelEntry({ item, selected, onSelect }: { item: TimelineChannel; selected: boolean; onSelect: () => void }) {
  const snippet = item.preview.replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim()
  return <Button variant="ghost" className="channel-entry" aria-pressed={selected} onClick={onSelect}>
    <span className="min-w-0 flex-1 text-left">
      <span className="flex items-baseline gap-2"><span className="min-w-0 flex-1 truncate font-semibold">{item.name}</span>{item.latest_at && <time className="shrink-0 text-caption text-muted-foreground" dateTime={item.latest_at} title={item.latest_at}>{formatRelativeTime(item.latest_at)}</time>}</span>
      <span className="mt-0.5 block text-caption text-muted-foreground">{channelLabel(item)}</span>
      <span className="mt-1 flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-sm font-normal text-muted-foreground">{snippet || '아직 저장된 게시물이 없습니다'}</span>{item.unread > 0 && <span className="channel-count channel-count-unread" title={`안 읽은 게시물 ${formatNumber(item.unread)} · 저장 ${formatNumber(item.count)}`}>{formatNumber(item.unread)}</span>}</span>
    </span>
  </Button>
}
