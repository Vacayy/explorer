// 문서 교차 종합 훅 (D-104) — 목록·단건 쿼리 + 생성 뮤테이션.
// 타입은 여기 co-locate (기능 로컬 타입 — useSaved 패턴).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"

export interface SynthesisDoc {
  id: number
  title: string | null
  source_type: string | null
  published_at: string | null
}

export interface Synthesis {
  id: number
  title: string | null
  body: string
  model: string | null
  created_at: string | null
  docs: SynthesisDoc[]
}

export interface SynthesisListItem {
  id: number
  title: string | null
  doc_count: number
  created_at: string | null
}

export const synthesisKeys = {
  list: () => ["spine", "synthesis"] as const,
  detail: (id: number | string) => ["spine", "synthesis", String(id)] as const,
}

/** 최근 종합 목록 — 일회성 산출물의 재열람 경로 (LLM 0) */
export function useSyntheses(limit = 5) {
  return useQuery(
    apiQuery<SynthesisListItem[]>({
      key: [...synthesisKeys.list(), limit],
      url: `/api/spine/synthesis?limit=${limit}`,
      staleTime: STALE.short,
    }),
  )
}

export function useSynthesis(id: string | undefined) {
  return useQuery({
    ...apiQuery<Synthesis>({
      key: synthesisKeys.detail(id ?? ""),
      url: `/api/spine/synthesis/${id}`,
      staleTime: STALE.short,
    }),
    enabled: !!id,
  })
}

/** 고른 문서들을 엮어 종합 생성 (sonnet, ~수십초) */
export function useCreateSynthesis() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (docIds: number[]) =>
      (await api.post("/api/spine/synthesis", { doc_ids: docIds })).data as Synthesis,
    onSuccess: () => qc.invalidateQueries({ queryKey: synthesisKeys.list() }),
  })
}
