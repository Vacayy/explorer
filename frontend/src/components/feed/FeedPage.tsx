import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronRight, Search, X } from 'lucide-react'
import { PageLayout } from '@/components/shared/PageLayout'
import { ErrorState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { InfoTip } from '@/components/regimes/Section'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Separator } from '@/components/ui/separator'
import { SystemPost } from '@/components/feed/FeedPost'
import { FeedRow } from '@/components/feed/FeedRow'
import { DocumentSearch } from '@/components/feed/DocumentSearch'
import { useFeedChipCounts, useFeedDocuments, useFeedTimeline } from '@/hooks/useFeed'
import { useMarkChannelRead, useTimelineChannels } from '@/hooks/useTimeline'
import { useFeedTopics } from '@/hooks/useFeedTopics'
import { FEED_CHIPS, feedChip, isQuiet, isSearchView, unreadIds, usesTimeline, type FeedChipKey } from '@/lib/feed'
import { groupDirectory } from '@/lib/canvas'
import { cn } from '@/lib/utils'
import { formatCountShort, formatKstDateTime, formatNumber } from '@/utils/format'
import type { EntityTag, TimelineChannel } from '@/types'

const PLATFORM = { telegram: '텔레그램', blog: '블로그', youtube: '유튜브', memo: '메모', system: 'Explorer' } as const
/** 피드 보기를 바꿀 때 지우는 문서 검색 쿼리 */
const SEARCH_KEYS = ['view', 'q', 'source', 'stock', 'industry', 'topic', 'page', 'days', 'sort']

/**
 * 피드 대메뉴 › 피드 (/feed · 시안 Feed, Feed-Search, Feed-Mobile · ia-redesign §4.5·§4.15·§4.28·§4.29).
 * 보기 전환 피드 | 문서 검색(view=documents). 피드 = 팔로우한 소스 | 소스 칩 + 글 목록 | 부상 종목 + Market Today.
 * 옛 /home?home_view=feed 주소의 쿼리(channel·channel_type·reader_topic·reader_until)를 그대로 읽는다.
 */
export default function FeedPage() {
  const [params, setParams] = useSearchParams()
  const searching = isSearchView(params.toString())
  const counts = useFeedChipCounts()
  const setView = (v: string) => setParams(prev => {
    const next = new URLSearchParams(prev)
    SEARCH_KEYS.forEach(k => next.delete(k))
    if (v === 'documents') next.set('view', 'documents')
    return next
  })
  return <PageLayout mode="document">
    <div className="space-y-5">
      <FeedHeader searching={searching} onView={setView} total={counts.all} />
      {searching ? <DocumentSearch /> : <FeedView counts={counts} />}
    </div>
  </PageLayout>
}

function FeedHeader({ searching, onView, total }: { searching: boolean; onView: (v: string) => void; total?: number }) {
  const navigate = useNavigate()
  const channels = useTimelineChannels()
  const unread = channels.data?.items.filter(c => c.platform !== 'system').reduce((s, c) => s + c.unread, 0)
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const q = new FormData(e.currentTarget).get('q')?.toString().trim()
    navigate(q ? `/feed?view=documents&q=${encodeURIComponent(q)}` : '/feed?view=documents')
  }
  return <header className="flex flex-wrap items-center gap-x-4 gap-y-3">
    <h1 className="text-page font-semibold">피드</h1>
    {!searching && unread != null && <span className="text-caption text-muted-foreground tabular-nums lg:hidden">안 읽음 {formatNumber(unread)}</span>}
    <SegmentTabs className="max-lg:hidden" tabs={[{ value: 'feed', label: '피드' }, { value: 'documents', label: '문서 검색' }]} value={searching ? 'documents' : 'feed'} onChange={onView} />
    {!searching && <>
      <form role="search" onSubmit={submit} className="relative ml-auto w-[320px] max-lg:hidden">
        <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input name="q" aria-label="문서 검색" autoComplete="off" className="rounded-full pl-9" placeholder={`문서 검색 — 전체 수집 자료 ${total != null ? `${formatCountShort(total)} 건` : ''}`} />
      </form>
      <Button variant="outline" size="icon" className="ml-auto rounded-full lg:hidden" aria-label="문서 검색" onClick={() => onView('documents')}><Search aria-hidden="true" /></Button>
    </>}
    {searching && <Button variant="ghost" size="sm" className="ml-auto lg:hidden" onClick={() => onView('feed')}>피드로</Button>}
  </header>
}

function FeedView({ counts }: { counts: Partial<Record<FeedChipKey, number>> }) {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [snapshot] = useState(() => new Date().toISOString())
  const until = params.get('reader_until') || snapshot
  const channel = params.get('channel') || ''
  const topic = params.get('reader_topic') || ''
  const chip = feedChip(params.toString())
  const timelineMode = usesTimeline(chip, channel)
  const directory = useTimelineChannels(until)
  const timeline = useFeedTimeline({ chip, channel, topic, until, enabled: timelineMode })
  const documents = useFeedDocuments(chip, !timelineMode)
  const list = timelineMode ? timeline : documents
  const markRead = useMarkChannelRead()
  const channels = useMemo(() => directory.data?.items ?? [], [directory.data])
  const selected = channels.find(c => c.id === channel)

  const patch = (values: Record<string, string | null>) => setParams(prev => {
    const next = new URLSearchParams(prev)
    Object.entries(values).forEach(([k, v]) => v == null ? next.delete(k) : next.set(k, v))
    return next
  })
  const pickChip = (key: FeedChipKey) => patch({ channel_type: key === 'all' ? null : key, channel: null, reader_topic: null })
  const pickChannel = (id: string) => patch({ channel: id || null, channel_type: null, reader_topic: null })
  const pickTopic = (name: string | null) => patch({ reader_topic: name, channel: null, channel_type: null })
  const clear = () => patch({ channel: null, channel_type: null, reader_topic: null })
  const onChip = (tag: EntityTag) => {
    if (tag.link_type === 'stock' && tag.aliases) navigate(`/feed?view=documents&stock=${encodeURIComponent(tag.aliases)}`)
    else if (tag.link_type === 'industry') navigate(`/feed?view=documents&industry=${encodeURIComponent(tag.name)}`)
    else if (tag.link_type === 'topic') navigate(`/feed?view=documents&topic=${encodeURIComponent(tag.name)}`)
    else navigate(`/feed?view=documents&q=${encodeURIComponent(tag.name)}`)
  }

  // 소스를 열어 글이 보이면 그 소스의 최신 시각까지 읽음으로 표시한다 (D-200). 주제로 거른 화면은 일부만 보여 표시하지 않는다(D-208)
  useEffect(() => {
    if (topic || !selected || selected.unread <= 0 || !selected.latest_at || !timeline.data || markRead.isPending) return
    markRead.mutate({ channel: selected.id, read_until: selected.latest_at })
  }, [topic, selected, timeline.data, markRead])

  const timelineItems = useMemo(() => timeline.data?.pages.flatMap(p => p.items) ?? [], [timeline.data])
  const unread = useMemo(() => unreadIds(timelineItems, channels), [timelineItems, channels])
  const unreadTotal = channels.filter(c => c.platform !== 'system').reduce((s, c) => s + c.unread, 0)
  const empty = timelineMode ? timeline.data && timelineItems.length === 0 : documents.data && documents.data.pages[0].items.length === 0

  return <div className="grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)_240px] xl:grid-cols-[260px_minmax(0,1fr)_260px] xl:gap-8">
    <SourceColumn channels={channels} loading={directory.isLoading} error={directory.isError} onRetry={() => void directory.refetch()}
      channel={channel} allActive={!channel && chip !== 'system'} unreadTotal={unreadTotal} onPick={pickChannel} onExplorer={() => pickChip('system')} />

    <section aria-label="글 목록" className="min-w-0 space-y-3 max-lg:order-3">
      <ChipStrip chip={chip} channel={channel} counts={counts} onPick={pickChip} />
      <MobileSources channels={channels} channel={channel} onPick={pickChannel} />
      <div className="lg:hidden"><Trending topic={topic} onPick={pickTopic} /></div>
      <div className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
        {selected && <span className="font-medium text-foreground">{selected.name}</span>}
        {chip === 'system' && !channel && <span className="font-medium text-foreground">Explorer 산출물</span>}
        {topic && <Button variant="secondary" size="xs" onClick={() => pickTopic(null)} aria-label={`주제 ${topic} 해제`}>{topic}<X aria-hidden="true" /></Button>}
        {timelineMode && chip !== 'system' && <span className="tabular-nums max-lg:hidden">안 읽음 {formatNumber(selected ? selected.unread : unreadTotal)}</span>}
        {(selected || topic || chip !== 'all') && <Button variant="link" size="xs" className="h-auto px-0 text-caption" onClick={clear}>전체 보기</Button>}
      </div>
      <Separator />
      {list.isLoading && <div role="status" aria-label="글 불러오는 중" className="space-y-6 py-3">{[1, 2, 3, 4].map(i => <div key={i} className="space-y-2"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-5 w-3/4" /><Skeleton className="h-12 w-full" /></div>)}</div>}
      {list.isError && !list.data && <ErrorState message="피드를 불러오지 못했습니다" onRetry={() => void list.refetch()} />}
      {empty && <div className="space-y-2 py-8 text-sm">
        <p className="text-muted-foreground">{topic ? `‘${topic}’ 주제의 글이 없습니다.` : selected ? '이 소스에 들어온 글이 없습니다.' : '조건에 맞는 글이 없습니다.'}</p>
        <Button variant="outline" size="sm" onClick={clear}>필터 지우기</Button>
      </div>}
      <div className={cn(list.isFetching && !list.isFetchingNextPage && list.data && 'opacity-60')}>
        {timelineMode
          ? timelineItems.map(item => item.document
            ? <FeedRow key={item.id} doc={item.document} unread={unread.has(item.id)} onChip={onChip} />
            : <div key={item.id} className="border-b"><SystemPost item={item} variant="row" /></div>)
          : documents.data?.pages.flatMap(p => p.items).map(doc => <FeedRow key={doc.id} doc={doc} onChip={onChip} />)}
      </div>
      {list.isError && list.data && <ErrorState message="더 불러오지 못했습니다" onRetry={() => void list.fetchNextPage()} />}
      {list.hasNextPage && <div className="border-t pt-3 text-center">
        <Button variant="ghost" size="sm" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>{list.isFetchingNextPage ? '불러오는 중…' : '더 불러오기'}</Button>
      </div>}
      {list.isFetchingNextPage && <div role="status" aria-label="더 불러오는 중" className="space-y-2"><Skeleton className="h-20 w-full" /><Skeleton className="h-20 w-full" /></div>}
    </section>

    <aside aria-label="부상 종목" className="space-y-4 max-lg:hidden">
      <Trending topic={topic} onPick={pickTopic} />
      <Button asChild variant="outline" className="h-auto w-full justify-between py-3 font-semibold"><Link to="/home">Market Today<ChevronRight aria-hidden="true" /></Link></Button>
    </aside>
  </div>
}

/** 왼쪽 칸 — 팔로우한 소스(전체 + 사람 소스, 안 읽은 수), Explorer 산출물은 맨 아래 한 줄. 새 글이 끊긴 소스는 흐리게 */
function SourceColumn({ channels, loading, error, onRetry, channel, allActive, unreadTotal, onPick, onExplorer }: {
  channels: TimelineChannel[]; loading: boolean; error: boolean; onRetry: () => void; channel: string; allActive: boolean
  unreadTotal: number; onPick: (id: string) => void; onExplorer: () => void
}) {
  const { human, explorer } = groupDirectory(channels)
  const explorerPosts = [...explorer.singles, ...explorer.groups.flatMap(g => g.items)].reduce((s, c) => s + c.count, 0)
  return <nav aria-label="팔로우한 소스" className="max-lg:hidden lg:sticky lg:top-4 lg:max-h-[calc(100dvh-var(--shell-offset))] lg:self-start lg:overflow-y-auto">
    <div className="flex items-center justify-between px-2 pb-2 text-caption text-muted-foreground">
      <h2 className="font-semibold">팔로우한 소스</h2>
      <Link to="/admin/sources" className="hover:text-foreground">소스 관리</Link>
    </div>
    <Button variant="ghost" aria-pressed={allActive} className="h-9 w-full justify-between px-2 font-semibold aria-pressed:bg-muted" onClick={() => onPick('')}>
      전체{unreadTotal > 0 && <span className="text-caption font-normal tabular-nums">{formatNumber(unreadTotal)}</span>}
    </Button>
    {loading && <div role="status" aria-label="소스 불러오는 중" className="space-y-2 px-2 pt-2">{[1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-6 w-full" />)}</div>}
    {error && <ErrorState message="소스 목록을 불러오지 못했습니다" onRetry={onRetry} />}
    {human.map(c => {
      const quiet = isQuiet(c.latest_at)
      return <Button key={c.id} variant="ghost" aria-pressed={channel === c.id} onClick={() => onPick(c.id)}
        className={cn('h-auto min-h-9 w-full justify-between gap-2 px-2 py-2 text-left font-normal aria-pressed:bg-muted', quiet && 'text-muted-foreground')}
        title={quiet && c.latest_at ? `${formatKstDateTime(c.latest_at).slice(0, 5)} 이후 새 글 없음` : undefined}>
        <span className="min-w-0 flex-1 truncate">{c.name}</span>
        {quiet && c.latest_at
          ? <span className="shrink-0 text-caption tabular-nums">{formatKstDateTime(c.latest_at).slice(0, 5)} 이후 없음</span>
          : <span className="flex shrink-0 items-center gap-3 text-caption text-muted-foreground"><span>{PLATFORM[c.platform]}</span><span className="w-8 text-right tabular-nums">{c.unread > 0 ? formatNumber(c.unread) : ''}</span></span>}
      </Button>
    })}
    {!loading && !error && human.length === 0 && <p className="px-2 py-3 text-sm text-muted-foreground">팔로우한 소스가 없어 전체 글을 보여 드려요.</p>}
    {explorer.count > 0 && <>
      <Separator className="my-2" />
      <Button variant="link" size="sm" className="h-auto px-2 text-caption font-normal text-muted-foreground" onClick={onExplorer}>
        Explorer 산출물(내러티브·컨콜 요약) {formatNumber(explorerPosts)}<ChevronRight aria-hidden="true" />
      </Button>
    </>}
  </nav>
}

/** 소스 칩 — 건수는 문서 수. '스크랩 · 미검증'은 구분선 뒤(전체에 섞지 않음). 모바일은 가로 스크롤 */
function ChipStrip({ chip, channel, counts, onPick }: { chip: FeedChipKey; channel: string; counts: Partial<Record<FeedChipKey, number>>; onPick: (k: FeedChipKey) => void }) {
  return <div role="group" aria-label="소스 종류" className="flex flex-wrap items-center gap-2 max-lg:-mx-4 max-lg:flex-nowrap max-lg:overflow-x-auto max-lg:px-4 max-lg:pb-1">
    {FEED_CHIPS.map(c => <span key={c.key} className="contents">
      {c.key === 'scrap' && <Separator orientation="vertical" className="h-6" />}
      <Button size="sm" variant={chip === c.key && !channel ? 'default' : 'outline'} aria-pressed={chip === c.key && !channel}
        className={cn('h-8 shrink-0 rounded-full px-3', c.key === 'scrap' && chip !== 'scrap' && 'border-dashed')} onClick={() => onPick(c.key)}>
        {c.label}{counts[c.key] != null && <span className="font-mono text-caption opacity-70">{formatCountShort(counts[c.key])}</span>}
      </Button>
    </span>)}
  </div>
}

/** 모바일 — 팔로우한 소스를 칩 한 줄(가로 스크롤)로 */
function MobileSources({ channels, channel, onPick }: { channels: TimelineChannel[]; channel: string; onPick: (id: string) => void }) {
  const human = channels.filter(c => c.platform !== 'system')
  if (human.length === 0) return null
  return <div role="group" aria-label="팔로우한 소스" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 lg:hidden">
    {human.map(c => <Button key={c.id} size="sm" variant={channel === c.id ? 'default' : 'secondary'} aria-pressed={channel === c.id}
      className={cn('h-8 shrink-0 font-normal', isQuiet(c.latest_at) && channel !== c.id && 'opacity-60')} onClick={() => onPick(c.id)}>
      {c.name}{c.unread > 0 && <span className="font-mono text-caption opacity-70">{formatNumber(c.unread)}</span>}
    </Button>)}
  </div>
}

/** 부상 종목 — 언급 모멘텀 상위. 누르면 그 이름으로 피드를 거른다(D-208). 로딩·오류·0건이면 블록을 생략한다(피드 본문과 독립) */
function Trending({ topic, onPick }: { topic: string; onPick: (name: string | null) => void }) {
  const { stocks } = useFeedTopics()
  if (stocks.length === 0) return null
  return <div className="space-y-2">
    <h2 className="flex items-center gap-1 text-sm font-semibold">부상 종목<InfoTip label="부상 종목 설명">최근 언급이 빠르게 늘어난 종목입니다. 누르면 그 종목 이야기만 피드에서 걸러 봅니다.</InfoTip></h2>
    <div className="flex flex-wrap gap-1.5 max-lg:flex-nowrap max-lg:overflow-x-auto">
      {stocks.map(name => <Button key={name} size="xs" variant={topic === name ? 'default' : 'outline'} aria-pressed={topic === name} className="shrink-0 font-normal"
        onClick={() => onPick(topic === name ? null : name)}>{name}</Button>)}
    </div>
  </div>
}
