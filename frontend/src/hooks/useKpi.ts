import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"

export interface KpiData {
  stock_code: string
  latest_year: number | null
  close: number | null
  price_change_pct: number | null
  market_cap: number | null
  per: number | null
  pbr: number | null
  op_margin: number | null
  op_margin_change: number | null
  roe: number | null
  roe_change: number | null
  revenue: number | null
  revenue_growth: number | null
  op_profit: number | null
  op_profit_growth: number | null
  net_income: number | null
  fwd_per: number | null
  fwd_fiscal_year?: string | null;
  fwd_eps: number | null
  target_price_consensus: number | null
}

export function useKpi(stockCode: string) {
  return useQuery<KpiData>({
    queryKey: ["kpi", stockCode],
    queryFn: async () => {
      const { data } = await api.get(`/api/kpi/${stockCode}`)
      return data
    },
    staleTime: 5 * 60_000,
  })
}
