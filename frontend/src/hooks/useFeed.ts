import { useQueries } from '@tanstack/react-query'
import { STALE } from '@/api/query'
import { fetchSpineFeed } from '@/api/spine'

/** 피드 머리 검색칸의 '전체 수집 자료 n건' — 문서 수(total)만 받는다. 스크랩(미검증)은 '전체'에 섞지 않으므로 뺀다. 실패하면 숫자 없이 둔다 */
export function useFeedTotal(): number | undefined {
  const [all, scrap] = useQueries({
    queries: [undefined, 'scrap'].map(source => ({
      queryKey: ['spine', 'feed', 'count', source ?? 'all'],
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchSpineFeed({ source, size: 1 }, signal),
      staleTime: STALE.medium,
    })),
  })
  return all.data && scrap.data ? all.data.total - scrap.data.total : undefined
}
