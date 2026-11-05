import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { MarketToday } from "@/types"

/** Market Today — 평일 회차(09:30·11:30·15:00·16:00 마감 정리) 화두 요약.
 *  date 없으면 오늘(KST, 자정에 넘어감), slot 없으면 그날 최신 회차 */
export function useMarketToday(slot?: string | null, date?: string | null) {
  const qs = new URLSearchParams()
  if (date) qs.set("date", date)
  if (slot) qs.set("slot", slot)
  const url = `/api/spine/market-today${qs.size ? `?${qs}` : ""}`
  return useQuery(apiQuery<MarketToday>({ key: ["spine", "market-today", date ?? "today", slot ?? "latest"], url, staleTime: STALE.short, keepPrevious: true }))
}
