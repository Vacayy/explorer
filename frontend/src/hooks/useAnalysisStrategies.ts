import { useQuery } from '@tanstack/react-query'
import { getJson } from '@/api/query'
import type { StrategyDefinition } from '@/components/analysis/types'

export function useAnalysisStrategies() {
  return useQuery({
    // This cache stores the full catalog envelope; group rules cache just its items.
    queryKey: ['market-analysis', 'strategy-definitions'],
    queryFn: ({ signal }) => getJson<{ version: string; items: StrategyDefinition[] }>('/api/analysis/strategies', undefined, { signal }),
    staleTime: 60_000,
  })
}
