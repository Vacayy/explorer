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

/** 홈 › 매크로 리스크 지표 묶음 — 금리·신용·심리 10개 계열의 5년 창(5년 위치 배지·6개월 추이선) */
export const RISK_TILE_KEYS = ['us2y', 'us10y', 'curve', 'hy', 'bbb', 'aaa', 'baa10y', 'aaa10y', 'vix', 'fear_greed'] as const
export function useRiskTiles() {
  return useQuery(apiQuery<RiskResponse>({
    key: ['spine', 'risk', 'window', '5y', RISK_TILE_KEYS.join(',')],
    url: `/api/spine/risk?range=5y&keys=${RISK_TILE_KEYS.join(',')}`, staleTime: STALE.short,
  }))
}
