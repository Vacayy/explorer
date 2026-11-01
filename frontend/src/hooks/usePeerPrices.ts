import { useQuery } from '@tanstack/react-query'
import { parsePeerPrices } from '@/lib/peerPerformance'

export function usePeerPrices() {
  return useQuery({
    queryKey: ['peer-price-snapshot'],
    queryFn: async () => parsePeerPrices((await import('@/data/peer-prices.json')).default),
    staleTime: Infinity,
    retry: false,
  })
}
