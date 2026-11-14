import { useQuery } from '@tanstack/react-query'
import { apiQuery } from '@/api/query'
import type { PublishedDocumentList } from '@/types'

export function usePublishedDocuments(q: string, cursor: string | null, enabled = true) {
  return useQuery({
    ...apiQuery<PublishedDocumentList>({
      key: ['public', 'documents', 'list', q, cursor],
      url: '/api/public/documents',
      params: { q, ...(cursor === null ? {} : { cursor }), limit: 10 },
      enabled,
      staleTime: 0,
    }),
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
  })
}
