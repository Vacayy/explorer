import { useQuery } from '@tanstack/react-query'
import { apiQuery, STALE } from '@/api/query'
import type { StockPriceItem } from '@/types'

export function usePublicCompanyPrices(code: string) {
  return useQuery(apiQuery<{ items: StockPriceItem[] }>({ key: ['public', 'company-prices', code],
    url: `/api/companies/${encodeURIComponent(code)}/prices`, enabled: !!code, staleTime: STALE.medium }))
}
