import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { TradeFollowRow, TradeHighlights, TradeStockItem } from "@/types"

/** 수출입 — 월 1회 적재되는 통계라 길게 캐시. 판정(flag·z·reason)은 서버가 요청 시 계산(D-140) */
export function useTradeFollows() {
  return useQuery(apiQuery<TradeFollowRow[]>({ key: ["spine", "trade", "follow"], url: "/api/spine/trade/follow", staleTime: STALE.medium }))
}
export function useTradeHighlights(limit = 5) {
  return useQuery(apiQuery<TradeHighlights>({ key: ["spine", "trade", "highlights", limit], url: `/api/spine/trade/highlights?limit=${limit}`, staleTime: STALE.long }))
}
/** 종목 → 품목 역링크 (trade_beneficiaries를 거꾸로) */
export function useTradeByStock(stockCode: string) {
  return useQuery(apiQuery<TradeStockItem[]>({ key: ["spine", "trade", "by-stock", stockCode], url: `/api/spine/trade/by-stock/${stockCode}`, staleTime: STALE.long }))
}
