import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getJson } from '@/api/query'
import { askQuestion } from '@/api/spine'
import { EXP_API, expKey } from '@/hooks/useExpectations'
import type { ReadingPage, ReadingHistory } from '@/types'

export function useMemoryReading(days: number, product: string, source: string) {
  return useQuery({ queryKey: [...expKey, 'reading', days, product, source],
    queryFn: () => getJson<ReadingPage>(`${EXP_API}/reading`, { days, product: product || undefined, source_type: source || undefined }),
    staleTime: 60_000 })
}
export function useReadingHistory(docId: number) {
  return useQuery({ queryKey: [...expKey, 'reading-history', docId], enabled: docId > 0,
    queryFn: () => getJson<ReadingHistory>(`${EXP_API}/reading/${docId}/history`), staleTime: 60_000 })
}
export function useReadingDiscussion() {
  const navigate = useNavigate()
  return useMutation({ mutationFn: ({ question, ids }: { question: string; ids: number[] }) => askQuestion({ question, document_ids: ids }),
    onSuccess: d => { if (d.conversation_id) navigate(`/chat?id=${d.conversation_id}`) } })
}
