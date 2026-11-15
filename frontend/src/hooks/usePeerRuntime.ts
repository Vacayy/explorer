import { useQuery } from '@tanstack/react-query'
import { apiQuery, STALE } from '@/api/query'
import { ApiError } from '@/api/query'
import api from '@/api/client'
import type { PeerRuntime } from '@/types/peer'

/** One published envelope prevents catalog and price revisions from being mixed. */
export function usePeerRuntime(generation?: string) {
  return useQuery({
    ...apiQuery<PeerRuntime>({ key: ['peer-runtime', generation], url: '/api/peers/runtime', staleTime: STALE.short }),
    queryFn: async ({ signal }) => {
      const response = await api.get<PeerRuntime>('/api/peers/runtime', { params: { generation }, signal })
      if (generation && response.headers['x-explorer-generation'] !== generation) throw new ApiError('조회하던 산업 자료가 갱신됐습니다.', 410)
      return response.data
    },
    refetchInterval: STALE.medium,
  })
}
