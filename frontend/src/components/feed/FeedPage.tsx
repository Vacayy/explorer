import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search } from 'lucide-react'
import { PageLayout } from '@/components/shared/PageLayout'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ChannelReader } from '@/components/feed/ChannelReader'
import { DocumentSearch } from '@/components/feed/DocumentSearch'
import { useFeedTotal } from '@/hooks/useFeed'
import { useTimelineChannels } from '@/hooks/useTimeline'
import { isSearchView } from '@/lib/feed'
import { cn } from '@/lib/utils'
import { formatCountShort, formatNumber } from '@/utils/format'

/** 피드 보기를 바꿀 때 지우는 문서 검색 쿼리 */
const SEARCH_KEYS = ['view', 'q', 'source', 'stock', 'industry', 'topic', 'page', 'days', 'sort']

/**
 * 피드 대메뉴 › 피드 (/feed · ia-redesign §4.5·§4.15 · D-325).
 * 보기 전환 피드 | 문서 검색(view=documents). 피드 = 옛 ChannelReader 구성(왼쪽 '내 피드' | 오른쪽 선택한 소스의 글).
 * 피드 보기는 화면 높이에 맞춘 틀 안에서 두 칸이 각자 스크롤한다(§4.34) — 문서 검색은 페이지 스크롤 그대로.
 */
export default function FeedPage() {
  const [params, setParams] = useSearchParams()
  const searching = isSearchView(params.toString())
  const total = useFeedTotal()
  const setView = (v: string) => setParams(prev => {
    const next = new URLSearchParams(prev)
    SEARCH_KEYS.forEach(k => next.delete(k))
    if (v === 'documents') next.set('view', 'documents')
    return next
  })
  return <PageLayout mode="document">
    <div className={cn('flex flex-col gap-5', !searching && 'md:h-[calc(100dvh-var(--shell-offset))] md:min-h-[520px]')}>
      <FeedHeader searching={searching} onView={setView} total={total} />
      {searching ? <DocumentSearch /> : <ChannelReader />}
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
  return <header className="flex flex-none flex-wrap items-center gap-x-4 gap-y-3">
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
