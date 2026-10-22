import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { TrendChart, TrendLeadersResponse } from "@/types"

/** 가파른 추세 종목 — 시세 최신일 기준 서버 계산(LLM 0) */
export function useTrendLeaders() {
  return useQuery(apiQuery<TrendLeadersResponse>({ key: ["spine", "trend-leaders"], url: "/api/spine/trend-leaders", staleTime: STALE.medium }))
}

/** 근거 창 차트 ≈ 2년 — 창을 열 때만 받는다(목록 응답을 가볍게) */
export function useTrendChart(code: string | undefined) {
  return useQuery({
    ...apiQuery<TrendChart>({ key: ["spine", "trend-leaders", "chart", code ?? ""], url: `/api/spine/trend-leaders/${code}/chart`, staleTime: STALE.medium }),
    enabled: !!code,
  })
}
