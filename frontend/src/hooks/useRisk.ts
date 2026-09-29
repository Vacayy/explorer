import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiQuery, postJson, STALE } from '@/api/query'
import type { RiskResponse, RiskSnapshotResponse } from '@/types'

// Version the expanded history contract so existing Home tabs discard the old 400-day response.
const KEY = ['spine', 'risk', 'history-v2'] as const

export function useRisk() {
  const client = useQueryClient()
  const query = useQuery({
    ...apiQuery<RiskResponse>({ key: KEY, url: '/api/spine/risk', staleTime: STALE.short }),
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
  })
  const snapshot = useMutation({
    mutationFn: () => postJson<RiskSnapshotResponse>('/api/spine/risk/snapshot', undefined, { timeout: 120_000 }),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  })
  return { ...query, refresh: () => snapshot.mutate(), refreshing: snapshot.isPending,
    refreshError: snapshot.error, snapshot: snapshot.data }
}
