import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
import type { StockPriceItem } from '@/types'

/** 도시에 차트·머리 공용 저장 시세(국내 stock_prices · 미국 us_prices) — 같은 키라 한 번만 부른다 */
export function useCompanyPrices(company: string, market: 'kr' | 'us') {
  return useQuery({
    queryKey: ['company-prices', company, market],
    queryFn: async ({ signal }) =>
      (await api.get<{ items: StockPriceItem[] }>('/api/spine/feed/company-prices', { params: { company, market }, signal })).data,
    staleTime: 300_000,
    enabled: !!company,
  })
}
