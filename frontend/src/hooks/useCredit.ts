import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { CreditHistory, CreditRow, CreditTable } from "@/types"

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

/** 1개월 스프레드 변화 내림차순(확대가 위) — 값 없음은 뒤 */
export const byWidening = (a: CreditRow, b: CreditRow) => (b.chg_1m ?? -Infinity) - (a.chg_1m ?? -Infinity)
