import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import type { KpiData } from "@/hooks/useKpi"

export interface CompareResponse {
  items: (KpiData & { corp_name?: string })[]
}

export function useCompare(stockCodes: string[]) {
  return useQuery<CompareResponse>({
    queryKey: ["compare", stockCodes],
    queryFn: () =>
      api.get("/api/compare", { params: { stocks: stockCodes.join(",") } }).then((r) => r.data),
    enabled: stockCodes.length >= 2,
  })
}
