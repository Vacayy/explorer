import { useQuery } from '@tanstack/react-query'
import { apiQuery, STALE } from '@/api/query'
import type { PublicMacroResponse } from '@/types'

export function usePublicMacro() {
  return useQuery(apiQuery<PublicMacroResponse>({
    key: ['public', 'macro'], url: '/api/spine/macro/public', staleTime: STALE.medium,
  }))
}
