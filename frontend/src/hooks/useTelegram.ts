import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";
import { toast } from "sonner";

export interface TelegramChannel {
  id: number;
  channel_name: string;
  display_name: string | null;
  is_active: number;
  last_fetched_at: string | null;
  added_at: string;
}

export function useTelegramChannels() {
  return useQuery<TelegramChannel[]>({
    queryKey: ["telegram-channels"],
    queryFn: async () => {
      const { data } = await api.get("/api/telegram/channels");
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export function useToggleTelegramChannel() {
  const qc = useQueryClient();
  return useMutation<TelegramChannel, Error, { id: number; is_active: boolean }>({
    mutationFn: async ({ id, is_active }) => {
      const { data } = await api.put(`/api/telegram/channels/${id}/toggle`, { is_active });
      return data;
    },
    onSuccess: (d, v) => {
      qc.invalidateQueries({ queryKey: ["telegram-channels"] });
      const name = d?.display_name ?? d?.channel_name ?? "채널";
      toast.success(v.is_active
        ? `'${name}' 수집 재개 — 다음 주기(30분)부터 수집됩니다`
        : `'${name}' 수집 중지 — 기존 수집분은 유지됩니다`);
    },
  });
}
