import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { SignalItem } from "@/types";

interface SignalsParams {
  stock_codes?: string;
  days?: number;
  type?: string;
}

export function useSignals(params: SignalsParams) {
  return useQuery<{ items: SignalItem[]; total: number }>({
    queryKey: ["signals", params],
    queryFn: async () => {
      const { data } = await api.get("/api/signals", { params });
      return data;
    },
    staleTime: 2 * 60_000,
  });
}
