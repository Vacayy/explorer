import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
import type { EvidenceRange, EvidenceResponse } from '@/types'

export interface EvidenceParams extends EvidenceRange {
  company: string
  market: 'kr' | 'us'
  source?: string
  q?: string
  page?: number
  size?: number
}

/** 기업 관련 자료(저장분만, LLM·외부 호출 0) — 목록·언급 흐름·기업활동 공시 칸이 같이 쓴다 */
export function useCompanyEvidence(params: EvidenceParams, enabled = true) {
  return useQuery({
    queryKey: ['company-evidence', params],
    queryFn: async ({ signal }) =>
      (await api.get<EvidenceResponse>('/api/spine/feed/company-evidence', { params, signal })).data,
    staleTime: 60_000,
    enabled: enabled && !!params.company,
  })
}
