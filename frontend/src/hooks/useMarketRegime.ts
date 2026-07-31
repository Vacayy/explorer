import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, postJson, STALE } from "@/api/query"
import type { MarketRegime } from "@/types"

const KEY = ["spine", "market-regime"] as const

/** 시장 국면 — 하루 1회 스냅샷(D-076). refresh=수동 스냅샷 적재(POST /snapshot) 후 갱신. */
export function useMarketRegime() {
  const qc = useQueryClient()
  const query = useQuery(apiQuery<MarketRegime>({ key: KEY, url: "/api/spine/market-regime", staleTime: STALE.long }))
  const refresh = useMutation({
    mutationFn: () => postJson("/api/spine/market-regime/snapshot"),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
  return { ...query, refresh: () => refresh.mutate(), refreshing: refresh.isPending }
}
