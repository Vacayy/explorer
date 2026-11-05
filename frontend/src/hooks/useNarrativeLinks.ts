import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, postJson, STALE } from "@/api/query"
import type { CandidateAction, NarrativeCandidates, NarrativeMarketToday } from "@/types"

/** 내러티브 상세 '장중 화두 타임라인' (ia-redesign §9.2) */
export function useNarrativeTimeline(narrativeId: number | null | undefined) {
  return useQuery(apiQuery<NarrativeMarketToday>({
    key: ["spine", "narrative-market-today", narrativeId], url: `/api/spine/narratives/${narrativeId}/market-today`,
    staleTime: STALE.short, enabled: narrativeId != null,
  }))
}

/** Thesis › 지금 '내러티브 후보' (§9.3) */
export function useNarrativeCandidates() {
  return useQuery(apiQuery<NarrativeCandidates>({ key: ["spine", "narrative-candidates"], url: "/api/spine/narrative-candidates", staleTime: STALE.short }))
}

/** [서사로 만들기·○○에 합치기] / [무시] — 생성은 하지 않는다(다음 내러티브 갱신 때 첫 버전) */
export function useCandidateAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ tag, action }: { tag: string; action: "approve" | "dismiss" }) =>
      postJson<CandidateAction>(`/api/spine/narrative-candidates/${encodeURIComponent(tag)}/${action}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["spine", "narrative-candidates"] })
      void qc.invalidateQueries({ queryKey: ["spine", "market-today"] })
    },
  })
}
