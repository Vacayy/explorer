import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import type { SearchResponse } from "@/components/shared/Omnibar"

/** 종목 추가용 검색 — 옴니바와 같은 통합 검색(/api/spine/search)에서 국내 종목·미국 티커만 쓴다 */
export function useStockSearch(q: string) {
  return useQuery({
    queryKey: ["spine", "search", "stocks", q],
    queryFn: async () => {
      const data = (await api.get<SearchResponse>("/api/spine/search", { params: { q, limit: 8 } })).data
      return { companies: data.companies, us: data.us }
    },
    enabled: q.length >= 1,
    staleTime: 60_000,
  })
}
