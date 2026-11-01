import { useQuery } from '@tanstack/react-query'
import { apiQuery, STALE } from '@/api/query'
import type { PeerRuntime } from '@/types/peer'

/** One published envelope prevents catalog and price revisions from being mixed. */
export function usePeerRuntime() {
  return useQuery({
    ...apiQuery<PeerRuntime>({ key: ['peer-runtime'], url: '/api/peers/runtime', staleTime: STALE.short }),
    refetchInterval: STALE.medium,
  })
}
