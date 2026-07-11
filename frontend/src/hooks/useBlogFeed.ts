import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";
import { toast } from "sonner";

export interface BlogSource {
  id: number;
  url: string;
  platform: string
  author: string | null;
  blog_name: string | null;
  is_active: number;
  last_fetched_at: string | null;
  added_at: string;
}

export function useBlogSources() {
  return useQuery<BlogSource[]>({
    queryKey: ["blog-sources"],
    queryFn: async () => {
      const { data } = await api.get("/api/blog/sources");
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export function useToggleBlogSource() {
  const qc = useQueryClient();
  return useMutation<BlogSource, Error, { id: number; is_active: boolean }>({
    mutationFn: async ({ id, is_active }) => {
      const { data } = await api.put(`/api/blog/sources/${id}/toggle`, { is_active });
      return data;
    },
    onSuccess: (d, v) => {
      qc.invalidateQueries({ queryKey: ["blog-sources"] });
      const name = d?.blog_name ?? "블로그";
      toast.success(v.is_active
        ? `'${name}' 표시 — 내 피드·AI 답변에 다시 노출됩니다`
        : `'${name}' 숨김 — 내 피드·AI 답변에서 제외됩니다 (수집은 계속)`);
    },
  });
}
