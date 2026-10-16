import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '@/api/client'
import type { StrategyDefinition } from '@/components/analysis/types'

export function useAnalysisStrategies() {
  return useQuery({
    // This cache stores the full catalog envelope; group rules cache just its items.
    queryKey: ['market-analysis', 'strategy-definitions'],
    queryFn: async ({ signal }): Promise<{ version: string; items: StrategyDefinition[] }> => {
      const response = await fetch(`${API_BASE}/api/analysis/strategies`, { signal })
      if (!response.ok) throw new Error('계산 조건을 불러오지 못했습니다.')
      return response.json()
    },
    staleTime: 60_000, retry: 1,
  })
}
