import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"

export interface IndexPerformanceData {
  stock_code: string
  market: string
  data: { date: string; stock: number | null; index: number | null }[]
}

export function useIndexPerformance(stockCode: string, days: number = 365) {
  return useQuery<IndexPerformanceData>({
    queryKey: ["index-performance", stockCode, days],
    queryFn: async () => {
      const { data } = await api.get(`/api/index/performance/${stockCode}`, { params: { days } })
      return data
    },
    staleTime: 5 * 60_000,
  })
}
