import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";

export interface TelegramChannel {
  id: number;
  channel_name: string;
  display_name: string | null;
  is_active: number;
  last_fetched_at: string | null;
  added_at: string;
}

export interface TelegramMessage {
  channel_name: string;
  message_id: string;
  content: string;
  date: string;
  link: string;
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

export function useTelegramFeed() {
  return useQuery<{ items: TelegramMessage[]; total: number }>({
    queryKey: ["telegram-feed"],
    queryFn: async () => {
      const { data } = await api.get("/api/telegram/feed");
      return data;
    },
    staleTime: 60_000,
  });
}

export function useAddTelegramChannel() {
  const qc = useQueryClient();
  return useMutation<TelegramChannel, Error, string>({
    mutationFn: async (url: string) => {
      const { data } = await api.post("/api/telegram/channels", { url });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["telegram-channels"] });
      qc.invalidateQueries({ queryKey: ["telegram-feed"] });
    },
  });
}

export function useToggleTelegramChannel() {
  const qc = useQueryClient();
  return useMutation<TelegramChannel, Error, { id: number; is_active: boolean }>({
    mutationFn: async ({ id, is_active }) => {
      const { data } = await api.put(`/api/telegram/channels/${id}/toggle`, { is_active });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["telegram-channels"] });
      qc.invalidateQueries({ queryKey: ["telegram-feed"] });
    },
  });
}

export function useDeleteTelegramChannel() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id: number) => {
      await api.delete(`/api/telegram/channels/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["telegram-channels"] });
      qc.invalidateQueries({ queryKey: ["telegram-feed"] });
    },
  });
}
