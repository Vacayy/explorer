// 문서 상세 관련 자료 (D-221·D-233) — 논점별 관련 자료(저장분 + 생성 트리거)와 유사도 기반 목록
import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import type { DocClaims, RelatedDoc } from '@/types'

const claimsKey = (docId: number) => ['spine', 'doc', docId, 'claims'] as const

/** 저장된 논점이 없으면(status=none) 한 번 자동으로 만들고, 만드는 동안 3초마다 다시 읽는다. */
export function useDocClaims(docId: number) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: claimsKey(docId),
    queryFn: async () => (await api.get<DocClaims>(`/api/spine/doc/${docId}/claims`)).data,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 3000 : false),
  })
  const build = useMutation({
    mutationFn: async () => (await api.post(`/api/spine/doc/${docId}/claims`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: claimsKey(docId) }),
  })
  const requested = useRef(new Set<number>())
  useEffect(() => {
    if (query.data?.status === 'none' && !requested.current.has(docId)) {
      requested.current.add(docId)
      build.mutate()
    }
  }, [query.data?.status, docId, build])
  return { ...query, build }
}

export function useRelatedDocs(docId: number) {
  return useQuery({
    queryKey: ['spine', 'doc', docId, 'related'],
    queryFn: async () => (await api.get<RelatedDoc[]>(`/api/spine/doc/${docId}/related`)).data,
    staleTime: 10 * 60_000,
  })
}
