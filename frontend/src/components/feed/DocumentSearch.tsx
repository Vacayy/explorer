import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { useSpineFeed } from '@/hooks/useSpineFeed'
import { ErrorState } from '@/components/shared/ErrorState'
import { FeedRow } from '@/components/feed/FeedRow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Separator } from '@/components/ui/separator'
import { SEARCH_SOURCES } from '@/lib/feed'
import { errorMessage } from '@/components/study/useStudy'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/utils/format'
import type { EntityTag } from '@/types'

const PERIODS = [{ key: '', label: '전체' }, { key: '30', label: '30일' }, { key: '7', label: '7일' }]
const SORTS = [{ key: 'relevance', label: '관련도' }, { key: 'latest', label: '최신' }]
const SOURCE_LABEL: Record<string, string> = { ...Object.fromEntries(SEARCH_SOURCES.map(s => [s.key, s.label])), scrap: '스크랩 · 미검증', memo: '메모', canon: '역사', note: '노트', people: '인물' }

/**
 * 피드 › 문서 검색 (view=documents · 시안 Feed-Search · ia-redesign §4.15). 의미 기반 + 단어 일치(하이브리드),
 * 소스·기간·정렬, 결과 강조, '이 결과로 대화'·'스터디로 모으기', 자주 같이 나온 종목·테마(검색 결과 전체 기준).
 * URL 쿼리(q·source·stock·industry·topic·days·sort·page)가 상태의 단일 소스.
 */
export function DocumentSearch() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const filters = {
    q: params.get('q') ?? undefined,
    source: params.get('source') ?? undefined,
    stock: params.get('stock') ?? undefined,
    industry: params.get('industry') ?? undefined,
    topic: params.get('topic') ?? undefined,
    days: params.get('days') ? Number(params.get('days')) : undefined,
    sort: params.get('sort') === 'latest' ? 'latest' as const : undefined,
    page: Math.max(1, Number(params.get('page') ?? '1') || 1),
    size: 20,
  }
  const query = useSpineFeed(filters)
  const data = query.data
  const set = (values: Record<string, string | null>) => setParams(prev => {
    const next = new URLSearchParams(prev)
    next.set('view', 'documents')
    Object.entries(values).forEach(([k, v]) => v ? next.set(k, v) : next.delete(k))
    if (!('page' in values)) next.delete('page')
    return next
  })
  const onChip = (tag: EntityTag) => {
    if (tag.link_type === 'stock' && tag.aliases) set({ stock: tag.aliases })
    else if (tag.link_type === 'industry') set({ industry: tag.name })
    else if (tag.link_type === 'topic') set({ topic: tag.name })
    else if (tag.link_type === 'person') navigate(`/person?name=${encodeURIComponent(tag.name)}`)
  }
  const active = (['stock', 'industry', 'topic'] as const).filter(k => filters[k])
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1
  const facets = data?.facets

  return <div className="space-y-4">
    <div className="flex flex-wrap items-center gap-2">
      <form role="search" className="relative min-w-0 flex-1 basis-80" onSubmit={e => {
        e.preventDefault()
        const v = new FormData(e.currentTarget).get('q')?.toString().trim() ?? ''
        set({ q: v || null })
      }}>
        <Search aria-hidden="true" className="absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input key={filters.q ?? ''} name="q" aria-label="문서 검색" autoComplete="off" autoFocus={!filters.q} defaultValue={filters.q ?? ''}
          placeholder="의미 기반 + 단어 일치로 찾기" className="h-12 rounded-xl pl-10 pr-10 text-base" />
        {filters.q && <Button type="button" variant="ghost" size="icon-xs" aria-label="검색어 지우기" onClick={() => set({ q: null, sort: null })}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground"><X /></Button>}
      </form>
      {filters.q && <div className="flex gap-2">
        <Button asChild variant="outline" size="sm" className="rounded-full"><Link to={`/chat?q=${encodeURIComponent(`'${filters.q}' 검색 결과를 바탕으로 정리해 주세요`)}`}>이 결과로 대화</Link></Button>
        <CollectToStudy q={filters.q} ids={data?.items.map(d => d.id) ?? []} />
      </div>}
    </div>

    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <div role="group" aria-label="소스" className="flex gap-1.5 overflow-x-auto max-md:-mx-4 max-md:px-4 max-md:pb-1">
        {SEARCH_SOURCES.map(s => {
          const on = (filters.source ?? 'all') === s.key
          return <Button key={s.key} size="sm" variant={on ? 'default' : 'outline'} aria-pressed={on} className="h-8 shrink-0 rounded-full px-3"
            onClick={() => set({ source: s.key === 'all' ? null : s.key })}>{s.label}</Button>
        })}
        {filters.source && !SOURCE_LABEL[filters.source] && <Button size="sm" aria-pressed className="h-8 shrink-0 rounded-full px-3" onClick={() => set({ source: null })}>{filters.source}<X aria-hidden="true" /></Button>}
      </div>
      <div className="flex items-center gap-1 text-caption text-muted-foreground md:ml-auto">
        <span className="pr-1">기간</span>
        {PERIODS.map(p => <Button key={p.key} size="xs" variant={String(filters.days ?? '') === p.key ? 'secondary' : 'ghost'} aria-pressed={String(filters.days ?? '') === p.key}
          onClick={() => set({ days: p.key || null })}>{p.label}</Button>)}
        {filters.q && <>
          <span className="pl-3 pr-1">정렬</span>
          {SORTS.map(s => <Button key={s.key} size="xs" variant={(filters.sort ?? 'relevance') === s.key ? 'secondary' : 'ghost'} aria-pressed={(filters.sort ?? 'relevance') === s.key}
            onClick={() => set({ sort: s.key === 'relevance' ? null : s.key })}>{s.label}</Button>)}
        </>}
      </div>
    </div>

    {active.length > 0 && <div className="flex flex-wrap items-center gap-2">
      {active.map(k => <Badge key={k} variant="secondary" className="gap-1 pr-1 text-xs">
        {k === 'stock' ? `종목 ${filters[k]}` : filters[k]}
        <Button variant="ghost" size="icon-xs" className="size-4" aria-label="필터 제거" onClick={() => set({ [k]: null })}><X className="size-3" /></Button>
      </Badge>)}
      <Button variant="ghost" size="xs" onClick={() => set({ stock: null, industry: null, topic: null })}>필터 지우기</Button>
    </div>}

    <div className={cn('grid gap-6', facets && 'lg:grid-cols-[minmax(0,1fr)_280px] xl:gap-8')}>
      <section aria-label="검색 결과" className="min-w-0">
        {data && <p className="pb-2 text-caption text-muted-foreground tabular-nums">
          {filters.q ? `'${filters.q}' ` : ''}{formatNumber(data.total)}건 · {filters.q ? (filters.sort === 'latest' ? '최신순' : '관련도순') : '최신순'}
        </p>}
        <Separator />
        {query.isLoading && <div role="status" aria-label="검색 중" className="space-y-6 py-4">{[1, 2, 3, 4].map(i => <div key={i} className="space-y-2"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-5 w-3/4" /><Skeleton className="h-12 w-full" /></div>)}</div>}
        {query.isError && <ErrorState message="문서를 불러오지 못했습니다" onRetry={() => void query.refetch()} />}
        {data && data.items.length === 0 && <div className="space-y-2 py-8 text-sm">
          <p className="text-muted-foreground">조건에 맞는 문서가 없습니다.</p>
          <div className="flex gap-2">
            {filters.days && <Button variant="outline" size="sm" onClick={() => set({ days: null })}>기간 넓히기</Button>}
            {(filters.source || active.length > 0) && <Button variant="outline" size="sm" onClick={() => set({ source: null, stock: null, industry: null, topic: null })}>필터 지우기</Button>}
          </div>
        </div>}
        <div className={cn(query.isPlaceholderData && 'opacity-60')}>
          {data?.items.map(doc => <FeedRow key={doc.id} doc={doc} q={filters.q} onChip={onChip} />)}
        </div>
        {data && totalPages > 1 && <nav aria-label="검색 결과 페이지" className="flex items-center justify-between border-t pt-3">
          <Button variant="outline" size="sm" disabled={filters.page <= 1} onClick={() => set({ page: String(filters.page - 1) })}>이전</Button>
          <span className="text-caption text-muted-foreground tabular-nums">{filters.page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={filters.page >= totalPages} onClick={() => set({ page: String(filters.page + 1) })}>다음</Button>
        </nav>}
      </section>
      {facets && <aside aria-label="검색 결과 묶음" className="space-y-5">
        {facets.entities.length > 0 && <div className="space-y-2">
          <h2 className="text-sm font-semibold">자주 같이 나온 종목·테마</h2>
          <div className="flex flex-wrap gap-1.5">
            {facets.entities.map(e => <Button key={`${e.link_type}-${e.name}`} size="xs" variant="outline" className="font-normal"
              onClick={() => onChip({ entity_id: 0, type: '', name: e.name, aliases: e.aliases, link_type: e.link_type, confidence: null })}>{e.name}</Button>)}
          </div>
        </div>}
        {Object.keys(facets.sources).length > 0 && <div className="space-y-1.5">
          <h2 className="text-sm font-semibold">소스별</h2>
          {Object.entries(facets.sources).sort((a, b) => b[1] - a[1]).map(([k, n]) => <div key={k} className="flex justify-between text-sm text-muted-foreground">
            <span>{SOURCE_LABEL[k] ?? k}</span><span className="tabular-nums">{formatNumber(n)}</span>
          </div>)}
        </div>}
      </aside>}
    </div>
  </div>
}

/** 스터디로 모으기 — 이 쪽 검색 결과를 새 스터디 프로젝트에 담고 그 프로젝트로 간다 */
function CollectToStudy({ q, ids }: { q: string; ids: number[] }) {
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const cache = useQueryClient()
  const run = async () => {
    setBusy(true)
    try {
      const { data } = await api.post<{ id: number }>('/api/spine/study-projects', { title: q.slice(0, 160) })
      await api.post(`/api/spine/study-projects/${data.id}/documents`, { document_ids: ids })
      await cache.invalidateQueries({ queryKey: ['spine', 'study-projects'] })
      toast.success(`스터디에 자료 ${ids.length}건을 모았습니다.`)
      navigate(`/study/projects/${data.id}`)
    } catch (e) { toast.error(errorMessage(e)) } finally { setBusy(false) }
  }
  return <Button variant="outline" size="sm" className="rounded-full" disabled={busy || ids.length === 0} onClick={() => void run()}>{busy ? '모으는 중…' : '스터디로 모으기'}</Button>
}
