import { useQuery } from '@tanstack/react-query'
import { apiQuery, STALE } from '@/api/query'
import type { PublicTradeResponse } from '@/types'

export function usePublicTrade(flow: 'export' | 'import', period: string | null, months: 24 | 60) {
  return useQuery({ ...apiQuery<PublicTradeResponse>({
    key: ['public', 'trade', flow, period, months], url: '/api/public/trade',
    params: { flow, months, ...(period ? { period } : {}) }, staleTime: STALE.medium,
  }), retry: false })
}
