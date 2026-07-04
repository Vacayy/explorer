import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"

export interface ConsensusEstimate {
  fiscal_year: string
  revenue_est: number | null
  op_profit_est: number | null
  net_income_est: number | null
  eps_est: number | null
  bps_est: number | null
  per_est: number | null
  target_price: number | null
  analyst_count: number | null
  opinion: string | null
}

export function useConsensus(stockCode: string) {
  return useQuery<{ stock_code: string; estimates: ConsensusEstimate[] }>({
    queryKey: ["consensus", stockCode],
    queryFn: async () => {
      const { data } = await api.get(`/api/consensus/${stockCode}`)
      return data
    },
    staleTime: 5 * 60_000,
  })
}
