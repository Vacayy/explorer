import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { DisclosureItem } from "@/types";

export function useDisclosures(
  stockCode: string,
  kind?: string,
  start?: string,
  end?: string,
  page: number = 1,
  size: number = 20
) {
  return useQuery<{ items: DisclosureItem[]; total: number }>({
    queryKey: ["disclosures", stockCode, kind, start, end, page, size],
    queryFn: async () => {
      const { data } = await api.get(`/api/disclosures/${stockCode}`, {
        params: { kind, start, end, page, size },
      });
      return data;
    },
    staleTime: 5 * 60_000,
  });
}
