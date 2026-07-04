import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";
import type { WatchlistItem } from "@/types";

export function useWatchlist() {
  return useQuery<WatchlistItem[]>({
    queryKey: ["watchlist"],
    queryFn: async () => {
      const { data } = await api.get("/api/watchlist");
      return data;
    },
    staleTime: 0,
  });
}

export function useAddToWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      stock_code: string;
      corp_code: string;
      corp_name: string;
      conviction: number;
      target_price?: number | null;
      thesis?: string | null;
    }) => {
      const { data } = await api.post("/api/watchlist", body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}

export function useUpdateWatchlistItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: {
      id: number;
      conviction?: number;
      target_price?: number | null;
      thesis?: string | null;
    }) => {
      const { data } = await api.put(`/api/watchlist/${id}`, body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}

export function useDeleteWatchlistItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/watchlist/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}
