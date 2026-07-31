import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, getJson, STALE } from "@/api/query"
import type { UsBriefing } from "@/types"

const KEY = ["spine", "us", "briefing"] as const

/** 어젯밤 미국장 브리핑 — 하루 1회 갱신(마감 후 크론 pre-warm). refresh=수동 force 갱신(TradingView+뉴스+재종합). */
export function useUsBriefing() {
  const qc = useQueryClient()
  const query = useQuery(apiQuery<UsBriefing>({ key: KEY, url: "/api/spine/us/briefing", staleTime: STALE.long }))
  const refresh = useMutation({
    mutationFn: () => getJson<UsBriefing>("/api/spine/us/briefing", { force: true }),
    onSuccess: (data) => qc.setQueryData(KEY, data),
  })
  return { ...query, refresh: () => refresh.mutate(), refreshing: refresh.isPending }
}
