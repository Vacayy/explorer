import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { StockPriceItem } from "@/types";

export function useStockPrices(stockCode: string, fromDate?: string, toDate?: string) {
  return useQuery<{ items: StockPriceItem[] }>({
    queryKey: ["stock-prices", stockCode, fromDate, toDate],
    queryFn: async () => {
      const { data } = await api.get(`/api/stock-prices/${stockCode}`, {
        params: { from_date: fromDate, to_date: toDate },
      });
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

