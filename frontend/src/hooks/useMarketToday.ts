import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { MarketToday } from "@/types"

/** Market Today — 장중 회차(10:00·13:00·15:40) 화두 요약. slot을 주면 그 회차, 없으면 그날 최신 회차 */
export function useMarketToday(slot?: string | null) {
  const url = slot ? `/api/spine/market-today?slot=${slot}` : "/api/spine/market-today"
  return useQuery(apiQuery<MarketToday>({ key: ["spine", "market-today", slot ?? "latest"], url, staleTime: STALE.short }))
}
