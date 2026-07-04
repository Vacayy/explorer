import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";
import type { IRNote } from "@/types";

export function useIRNotes(stockCode: string, memoType?: string) {
  return useQuery<IRNote[]>({
    queryKey: ["ir-notes", stockCode, memoType],
    queryFn: async () => {
      const params: Record<string, string> = {}
      if (memoType) params.memo_type = memoType
      const { data } = await api.get(`/api/ir-notes/${stockCode}`, { params });
      return data;
    },
    staleTime: 0,
  });
}

export function useCreateIRNote(stockCode: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { title: string; content?: string; note_date: string; memo_type?: string }) => {
      const { data } = await api.post(`/api/ir-notes/${stockCode}`, body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ir-notes", stockCode] }),
  });
}

export function useUpdateIRNote(stockCode: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: number; title?: string; content?: string; note_date?: string }) => {
      const { data } = await api.put(`/api/ir-notes/${id}`, body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ir-notes", stockCode] }),
  });
}

export function useDeleteIRNote(stockCode: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/ir-notes/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ir-notes", stockCode] }),
  });
}
