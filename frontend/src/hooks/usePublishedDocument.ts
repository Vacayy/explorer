import { useQuery } from '@tanstack/react-query'
import { apiQuery } from '@/api/query'
import type { PublishedDocument } from '@/types'

export function usePublishedDocument(docId: number | null) {
  return useQuery({
    ...apiQuery<PublishedDocument>({
      key: ['public', 'documents', docId],
      url: `/api/public/documents/${docId}`,
      enabled: docId !== null,
      staleTime: 0,
    }),
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
  })
}
