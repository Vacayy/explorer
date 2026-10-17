import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { TrendLeadersResponse } from "@/types"

/** 가파른 추세 종목 — 시세 최신일 기준 서버 계산(LLM 0) */
export function useTrendLeaders() {
  return useQuery(apiQuery<TrendLeadersResponse>({ key: ["spine", "trend-leaders"], url: "/api/spine/trend-leaders", staleTime: STALE.medium }))
}
