import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { CreditHistory, CreditTable } from "@/types"

/** 회사채 스프레드(D-230) — 저장분 읽기만. 하루 1회 수집이라 길게 캐시. */
export function useCreditTable() {
  return useQuery(apiQuery<CreditTable>({ key: ["spine", "credit"], url: "/api/spine/credit", staleTime: STALE.long }))
}
export function useCreditHistory(tickers: string[]) {
  const key = tickers.join(",")
  return useQuery({
    ...apiQuery<CreditHistory>({ key: ["spine", "credit", "history", key], url: `/api/spine/credit/history?tickers=${encodeURIComponent(key)}`, staleTime: STALE.long }),
    enabled: tickers.length > 0,
  })
}
