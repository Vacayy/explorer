import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"

export interface ScreenerParams {
  per_max?: number
  pbr_max?: number
  opm_min?: number
  roe_min?: number
  rev_growth_min?: number
  mcap_tier?: "small" | "mid" | "large" | "all"
  sort?: string
  sort_dir?: "asc" | "desc"
  limit?: number
}

export interface ScreenerItem {
  stock_code: string
  corp_name: string
  market_cap: number | null
  per: number | null
  pbr: number | null
  op_margin: number | null
  revenue_growth: number | null
  op_profit_growth: number | null
  roe: number | null
  latest_close: number | null
}

export interface ScreenerResponse {
  items: ScreenerItem[]
  total: number
  filtered_from: number
}

export function useScreener(params: ScreenerParams) {
  return useQuery<ScreenerResponse>({
    queryKey: ["screener", params],
    queryFn: async () => {
      const { data } = await api.get("/api/screener", { params })
      return data
    },
    staleTime: 60_000,
  })
}
