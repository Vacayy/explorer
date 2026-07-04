import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";
import type { CatalystItem } from "@/types";

export function useCatalysts(days?: number) {
  return useQuery<CatalystItem[]>({
    queryKey: ["catalysts", days],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (days !== undefined) params.days = String(days);
      const { data } = await api.get("/api/catalysts", { params });
      return data;
    },
    staleTime: 0,
  });
}

export function useCreateCatalyst() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      stock_code?: string | null;
      event_type: string;
      event_date: string;
      title: string;
      description?: string | null;
    }) => {
      const { data } = await api.post("/api/catalysts", body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalysts"] }),
  });
}

export function useDeleteCatalyst() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/catalysts/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalysts"] }),
  });
}
