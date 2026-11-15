import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { Company } from "@/types";

export function useCompanySearch(query: string) {
  return useQuery<Company[]>({
    queryKey: ["companies", "search", query],
    queryFn: async ({ signal }) => {
      if (!query || query.length < 1) return [];
      const { data } = await api.get("/api/companies/search", {
        signal,
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
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/api/companies/${stockCode}`, { signal });
      return data;
    },
    enabled: !!stockCode,
    staleTime: Infinity,
  });
}
