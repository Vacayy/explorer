import { useQuery } from '@tanstack/react-query'
import { apiQuery } from '@/api/query'
import type { PublicFeed } from '@/types'

export function usePublicFeed(filters: { channel: string; platform: string; topic: string; page: number; until: string }) {
  return useQuery({
    ...apiQuery<PublicFeed>({ key: ['public', 'feed', filters], url: '/api/public/feed', params: filters, staleTime: 0 }),
    gcTime: 0, retry: false, refetchOnMount: 'always', refetchOnWindowFocus: 'always',
  })
}
