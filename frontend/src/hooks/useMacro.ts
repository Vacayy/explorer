import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, postJson, STALE } from "@/api/query"
import type { MacroData } from "@/types"

const KEY = ["spine", "macro"] as const

/** 매크로·유동성 — 하루 1회 스냅샷(버튼 주도). refresh=수동 재수집(POST /snapshot) 후 갱신. */
export function useMacro() {
  const qc = useQueryClient()
  const query = useQuery(apiQuery<MacroData>({ key: KEY, url: "/api/spine/macro", staleTime: STALE.long }))
  const refresh = useMutation({
    mutationFn: () => postJson("/api/spine/macro/snapshot"),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
  return { ...query, refresh: () => refresh.mutate(), refreshing: refresh.isPending }
}
