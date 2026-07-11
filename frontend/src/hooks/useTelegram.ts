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
        ? `'${name}' 표시 — 내 피드·AI 답변에 다시 노출됩니다`
        : `'${name}' 숨김 — 내 피드·AI 답변에서 제외됩니다`);
    },
  });
}
