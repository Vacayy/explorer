import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { TwLinksResponse, TwRevenueResponse } from "@/types"

/** 대만 월매출 91개사 — 저장분 읽기(수집은 매일 11:00 launchd twrevenue) */
export function useTwRevenue() {
  return useQuery(apiQuery<TwRevenueResponse>({ key: ["spine", "tw", "revenue"], url: "/api/spine/tw/revenue", staleTime: STALE.long }))
}

/** 대만 → 한국 연결 신호 — kr를 주면 그 종목 연결만 */
export function useTwLinks(kr?: string) {
  return useQuery(apiQuery<TwLinksResponse>({
    key: ["spine", "tw", "links", kr ?? "all"], url: "/api/spine/tw/links", params: kr ? { kr } : undefined, staleTime: STALE.long,
  }))
}
