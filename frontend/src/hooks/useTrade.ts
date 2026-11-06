import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { TradeFollowRow, TradeGrid, TradeHighlights, TradeStockItem } from "@/types"

/** 수출입 — 월 1회 적재되는 통계라 길게 캐시. 판정(flag·z·reason)은 서버가 요청 시 계산(D-140) */
export function useTradeFollows() {
  return useQuery(apiQuery<TradeFollowRow[]>({ key: ["spine", "trade", "follow"], url: "/api/spine/trade/follow", staleTime: STALE.medium }))
}
export function useTradeHighlights(limit = 5, period?: string | null) {
  return useQuery(apiQuery<TradeHighlights>({ key: ["spine", "trade", "highlights", limit, period ?? "latest"],
    url: `/api/spine/trade/highlights?limit=${limit}${period ? `&period=${encodeURIComponent(period)}` : ""}`, staleTime: STALE.long }))
}
/** 종목 → 품목 역링크 (trade_beneficiaries를 거꾸로) */
export function useTradeByStock(stockCode: string) {
  return useQuery(apiQuery<TradeStockItem[]>({ key: ["spine", "trade", "by-stock", stockCode], url: `/api/spine/trade/by-stock/${stockCode}`, staleTime: STALE.long }))
}
/** 품목 벽 — 팔로우 품목(세목 제외) 전체 시계열을 한 번에(칸마다 /trade/{hs}를 부르지 않는다). months 24 = 2년 · 60 = 5년 */
export function useTradeGrid(months: 24 | 60) {
  return useQuery(apiQuery<TradeGrid>({ key: ["spine", "trade", "grid", months], url: `/api/spine/trade/grid?months=${months}`, staleTime: STALE.medium, keepPrevious: true }))
}
