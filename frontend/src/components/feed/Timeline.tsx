import { useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowUpRight, RefreshCw, Rss } from 'lucide-react'
import { useTimeline } from '@/hooks/useTimeline'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ErrorState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { PageHeader } from '@/components/shared/PageLayout'
import { FreshnessStamp } from '@/components/shared/FreshnessStamp'
import { DocumentCard, SystemPost } from './FeedPost'
import type { EntityTag } from '@/types'

const scopes = [{ value: 'all', label: '전체' }, { value: 'sources', label: '소스' }, { value: 'system', label: 'Explorer' }]
const kinds = [{ value: 'all', label: '모든 업데이트' }, { value: 'company', label: '기업 요약' }, { value: 'person', label: '인물 요약' }, { value: 'transcript', label: '컨콜' }, { value: 'trade', label: '수출입' }]
const sources = [{ value: 'all', label: '모든 소스' }, { value: 'telegram', label: '텔레그램' }, { value: 'blog', label: '블로그·뉴스' }, { value: 'youtube', label: '유튜브' }]
const valid = (v: string | null, options: { value: string }[]) => options.some(x => x.value === v) ? v! : 'all'

export function Timeline({ embedded = false }: { embedded?: boolean }) {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const top = useRef<HTMLHeadingElement>(null)
  const scope = valid(params.get('feed_scope'), scopes)
  const kind = scope === 'system' ? valid(params.get('feed_kind'), kinds) : 'all'
  const source = scope === 'sources' ? valid(params.get('feed_source'), sources) : 'all'
  const rawPage = Number(params.get('feed_page') || 1)
  const page = Number.isInteger(rawPage) && rawPage >= 1 && rawPage <= 100 ? rawPage : 1
  const rawUntil = params.get('feed_until')
  const until = rawUntil && Number.isFinite(Date.parse(rawUntil)) ? new Date(rawUntil).toISOString() : undefined
  const compact = params.get('feed_density') === 'compact'
  const { data, isLoading, isError, isFetching, refetch } = useTimeline({ scope, kind, source, page, until })

  function change(key: string, value: string) {
    setParams(prev => {
      const next = new URLSearchParams(prev)
      value === 'all' ? next.delete(key) : next.set(key, value)
      if (key !== 'feed_density') { next.delete('feed_page'); next.delete('feed_until') }
      return next
    })
  }
  function goPage(nextPage: number) {
    setParams(prev => { const next = new URLSearchParams(prev); next.set('feed_page', String(nextPage)); if (data) next.set('feed_until', data.until); return next })
    top.current?.focus({ preventScroll: true })
    top.current?.scrollIntoView({ block: 'start' })
  }
  function onTag(tag: EntityTag) {
    if (tag.link_type === 'person') navigate(`/person?name=${encodeURIComponent(tag.name)}`)
    else if (tag.link_type === 'stock' && tag.aliases) navigate(`/feed?stock=${encodeURIComponent(tag.aliases)}`)
    else if (tag.link_type === 'industry' || tag.link_type === 'topic') navigate(`/feed?${tag.link_type}=${encodeURIComponent(tag.name)}`)
  }
  const fullParams = new URLSearchParams(params)
  fullParams.delete('home_view')

  return (
    <section aria-labelledby="timeline-title" className="timeline-surface min-w-0 space-y-4">
      <PageHeader title="피드" level={embedded ? 2 : 1} id="timeline-title" titleRef={top}
        description="팔로우한 소스의 새 글과 Explorer 업데이트"
        actions={<Button asChild variant="ghost" size="sm" className="glass-surface text-caption"><Link to={embedded ? `/feed?${fullParams}` : '/feed?view=documents'}>{embedded ? '크게 보기' : '문서 검색'}<ArrowUpRight aria-hidden="true" className="size-3" /></Link></Button>} />
      <div className="space-y-3 border-b pb-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SegmentTabs tabs={scopes} value={scope} onChange={v => change('feed_scope', v)} />
          <Button variant="ghost" size="icon"  aria-label="최신 피드 새로고침" disabled={isFetching} onClick={() => {
            if (page !== 1 || until) setParams(prev => { const next = new URLSearchParams(prev); next.delete('feed_page'); next.delete('feed_until'); return next })
            else void refetch()
          }}><RefreshCw aria-hidden="true" className={`size-3.5 ${isFetching ? 'motion-safe:animate-spin' : ''}`} /></Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {scope !== 'all' ? <Select value={scope === 'system' ? kind : source} onValueChange={v => change(scope === 'system' ? 'feed_kind' : 'feed_source', v)}>
            <SelectTrigger aria-label={scope === 'system' ? '업데이트 종류' : '소스 종류'} className="w-40 text-caption"><SelectValue /></SelectTrigger>
            <SelectContent>{(scope === 'system' ? kinds : sources).map(x => <SelectItem key={x.value} value={x.value}>{x.label}</SelectItem>)}</SelectContent>
          </Select> : <span className="text-xs text-muted-foreground">최신순 · 원문과 요약을 함께</span>}
          <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted-foreground" htmlFor="feed-compact">간결하게<Switch id="feed-compact" checked={compact} onCheckedChange={v => change('feed_density', v ? 'compact' : 'all')} /></label>
        </div>
      </div>
      {scope === 'system' && <p className="text-xs leading-relaxed text-muted-foreground">시스템이 저장한 기업·인물 요약과 구독 중인 컨콜·수출입입니다. 표기된 기준 기간을 함께 확인하세요.</p>}
      {isError && <ErrorState message={data ? '새로고침에 실패했습니다. 이전 피드를 표시합니다.' : '피드를 불러오지 못했습니다.'} onRetry={() => refetch()} />}
      {isLoading && <div role="status" aria-label="피드 불러오는 중" className="space-y-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-52 rounded-xl" />)}</div>}
      {data && data.items.length === 0 && <div className="rounded-xl bg-card p-6 text-center ring-1 ring-border/60">
        <Rss aria-hidden="true" className="mx-auto mb-3 size-6 text-muted-foreground" />
        <p className="text-sm font-medium">아직 표시할 업데이트가 없습니다</p>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{scope === 'system' ? '저장된 요약이나 수집 자료가 생기면 여기에 표시됩니다.' : '소스를 팔로우하면 수집된 글이 여기에 모입니다.'}</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2"><Button variant="outline" size="sm" onClick={() => change('feed_scope', 'all')}>전체 피드</Button><Button asChild variant="ghost" size="sm"><Link to="/follow">팔로우 관리</Link></Button></div>
      </div>}
      {data && <div>{data.items.map(item => item.document
        ? <DocumentCard key={item.id} doc={item.document} onChipFilter={onTag} variant="row" compact={compact} timeLabel={item.time_label} />
        : <SystemPost key={item.id} item={item} variant="row" compact={compact} />)}</div>}
      {data && <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <div className="space-y-1 text-caption text-muted-foreground"><p aria-live="polite">{page}페이지 · {data.items.length}개 업데이트</p><FreshnessStamp asOf={data.as_of} /></div>
        <div className="flex gap-2"><Button variant="outline" size="sm" disabled={page <= 1 || isFetching} onClick={() => goPage(page - 1)}>이전</Button><Button variant="outline" size="sm" disabled={!data.has_more || page >= 100 || isFetching} onClick={() => goPage(page + 1)}>다음</Button></div>
      </div>}
    </section>
  )
}
