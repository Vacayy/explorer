import { useQuery } from '@tanstack/react-query'
import { parsePeerCatalog } from '@/lib/peerCatalog'

/** Versioned public research bundle; does not fetch prices or touch the backend. */
export function usePeerCatalog() {
  return useQuery({
    queryKey: ['peer-catalog'],
    queryFn: async () => parsePeerCatalog((await import('@/data/peer-catalog.json')).default),
    staleTime: Infinity,
    retry: false,
  })
}
