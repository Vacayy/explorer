import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { TwRevenueResponse } from "@/types"

/** 대만 월매출 91개사 — 저장분 읽기(수집은 매일 11:00 launchd twrevenue) */
export function useTwRevenue() {
  return useQuery(apiQuery<TwRevenueResponse>({ key: ["spine", "tw", "revenue"], url: "/api/spine/tw/revenue", staleTime: STALE.long }))
}
