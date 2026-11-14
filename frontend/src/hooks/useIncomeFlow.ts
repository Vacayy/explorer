import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import type { IncomeFlowQuarters, IncomeFlowResponse } from "@/types"

// 국내: /api/financials/:code/income-flow[?q=YY.MM] · 미국: /api/spine/us/:ticker/income-flow[?q=YYYY-MM]
// 라우트가 둘인 이유: 국내는 corp_code 해소·사업보고서 차감 로직, 미국은 SEC companyfacts 분기 분해로 원천이 다르다

const BASE = { kr: "/api/financials", us: "/api/spine/us" } as const

export function useIncomeFlow(code: string, market: "kr" | "us", q: string | null, mode: "q" | "ttm" = "q") {
  return useQuery<IncomeFlowResponse>({
    queryKey: ["income-flow", market, code, q, mode],
    queryFn: async () => {
      const params: Record<string, string> = {}
      if (q) params.q = q
      if (mode === "ttm") params.mode = "ttm"
      return (await api.get(`${BASE[market]}/${code}/income-flow`, { params })).data
    },
    staleTime: 10 * 60_000,
    enabled: !!code,
  })
}

export function useIncomeFlowQuarters(code: string, market: "kr" | "us") {
  return useQuery<IncomeFlowQuarters>({
    queryKey: ["income-flow-quarters", market, code],
    queryFn: async () => (await api.get(`${BASE[market]}/${code}/income-flow/quarters`)).data,
    staleTime: 60 * 60_000,
    enabled: !!code,
  })
}

// 트리거 — 보유·관심·시총 상위 밖인 소형주의 재무를 DART에서 즉시 받는다. 현재는 국내만(미국은 SEC 백필 범위 백로그)
interface CollectStats {
  stock_code: string
  periods_added: number
  rows: number
  no_data: number
  failed: number
  calls: number
}
export function useFinancialsCollect(code: string) {
  const qc = useQueryClient()
  return useMutation<CollectStats>({
    mutationFn: async () => (await api.post(`/api/financials/${code}/collect`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["income-flow", "kr", code] })
      qc.invalidateQueries({ queryKey: ["income-flow-quarters", "kr", code] })
      qc.invalidateQueries({ queryKey: ["financials", code] })
    },
  })
}
