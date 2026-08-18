import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, getJson, STALE } from "@/api/query"
import type { KrMovers } from "@/types"

const KEY = ["spine", "kr", "movers"] as const

/** 전일 국장 거래대금 상위 — 로드는 순수 읽기, refresh=수동 force 재수집 (D-100 버튼 주도, D-108). */
export function useKrMovers() {
  const qc = useQueryClient()
  const query = useQuery(apiQuery<KrMovers>({ key: KEY, url: "/api/spine/kr/movers", staleTime: STALE.long }))
  const refresh = useMutation({
    mutationFn: () => getJson<KrMovers>("/api/spine/kr/movers", { force: true }),
    onSuccess: (data) => qc.setQueryData(KEY, data),
  })
  return { ...query, refresh: () => refresh.mutate(), refreshing: refresh.isPending }
}
