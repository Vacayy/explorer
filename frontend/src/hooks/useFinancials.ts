import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { FinancialResponse } from "@/types";

export function useFinancials(
  stockCode: string,
  sj_div: string,
  period: string,
  years: number,
  fs_div: string = "CFS",
  options?: { enabled?: boolean }
) {
  return useQuery<FinancialResponse>({
    queryKey: ["financials", stockCode, sj_div, period, years, fs_div],
    queryFn: async () => {
      const { data } = await api.get(`/api/financials/${stockCode}`, {
        params: { sj_div, period, years, fs_div },
      });
      return data;
    },
    staleTime: 5 * 60_000,
    enabled: options?.enabled,
  });
}
