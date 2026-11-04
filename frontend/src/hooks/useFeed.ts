import { useInfiniteQuery, useQueries } from '@tanstack/react-query'
import { getJson, STALE } from '@/api/query'
import { fetchSpineFeed } from '@/api/spine'
import { FEED_CHIPS, type FeedChipKey } from '@/lib/feed'
import type { TimelineResponse } from '@/types'

const PAGE = 20

/** 피드 가운데 글 목록 — 타임라인(안 읽음·소스 선택·주제 칩), '더 불러오기'로 이어 붙인다 (ia-redesign §4.5) */
export function useFeedTimeline({ chip, channel, topic, until, enabled }: { chip: FeedChipKey; channel: string; topic: string; until: string; enabled: boolean }) {
  const system = chip === 'system'
  return useInfiniteQuery({
    queryKey: ['spine', 'timeline', 'feed', { chip, channel, topic, until }],
    queryFn: ({ pageParam }) => getJson<TimelineResponse>('/api/spine/feed/timeline', {
      scope: system ? 'system' : 'sources', kind: 'all', source: system || chip === 'all' ? 'all' : chip,
      channel: channel || undefined, topic: topic || undefined, page: pageParam, size: PAGE, until,
    }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.has_more && pages.length < 100 ? pages.length + 1 : undefined),
    staleTime: STALE.medium,
    enabled,
  })
}

/** 문서 분류 소스(뉴스·아티클·컨콜·인물·역사·블로그·스크랩)의 최신 글 — 문서 코퍼스 최신순 */
export function useFeedDocuments(source: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ['spine', 'feed', 'chip', source],
    queryFn: ({ pageParam, signal }) => fetchSpineFeed({ source, page: pageParam, size: PAGE }, signal),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page * last.size < last.total ? last.page + 1 : undefined),
    staleTime: STALE.medium,
    enabled,
  })
}

/** 소스 칩 옆 건수 — 칩마다 문서 수(total)만 받는다. 실패한 칩은 숫자 없이 둔다 */
export function useFeedChipCounts(): Partial<Record<FeedChipKey, number>> {
  const results = useQueries({
    queries: FEED_CHIPS.map(c => ({
      queryKey: ['spine', 'feed', 'count', c.key],
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchSpineFeed({ source: c.key === 'all' ? undefined : c.key, size: 1 }, signal),
      staleTime: STALE.medium,
    })),
  })
  const counts: Partial<Record<FeedChipKey, number>> = Object.fromEntries(FEED_CHIPS.flatMap((c, i) => results[i].data ? [[c.key, results[i].data!.total]] : []))
  // 스크랩(미검증)은 '전체'에 섞지 않는다 — 전체 건수에서도 뺀다
  if (counts.all != null) counts.all = counts.scrap != null ? counts.all - counts.scrap : undefined
  return counts
}
