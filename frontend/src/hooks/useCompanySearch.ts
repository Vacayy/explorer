import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { Company } from "@/types";

export function useCompanySearch(query: string) {
  return useQuery<Company[]>({
    queryKey: ["companies", "search", query],
    queryFn: async () => {
      if (!query || query.length < 1) return [];
      const { data } = await api.get("/api/companies/search", {
        params: { q: query },
      });
      return data;
    },
    enabled: query.length >= 1,
    staleTime: 60_000,
  });
}

export function useCompany(stockCode: string | null) {
  return useQuery<Company>({
    queryKey: ["companies", stockCode],
    queryFn: async () => {
      const { data } = await api.get(`/api/companies/${stockCode}`);
      return data;
    },
    enabled: !!stockCode,
    staleTime: Infinity,
  });
}
