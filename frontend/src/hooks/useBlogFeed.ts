import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";

export interface BlogSource {
  id: number;
  url: string;
  platform: string;
  blog_name: string | null;
  is_active: number;
  last_fetched_at: string | null;
  added_at: string;
}

export interface BlogTag {
  type: string;
  value: string;
}

export interface BlogPost {
  id: number;
  source_id: number;
  title: string;
  summary: string | null;
  author: string | null;
  url: string | null;
  published_at: string | null;
  fetched_at: string;
  blog_name: string | null;
  platform: string;
  tags?: BlogTag[];
}

export interface BlogPostFull extends BlogPost {
  content: string | null;
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

export function useBlogFeed(tag?: string) {
  return useQuery<{ items: BlogPost[]; total: number }>({
    queryKey: ["blog-feed", tag],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (tag) params.tag = tag;
      const { data } = await api.get("/api/blog/feed", { params });
      return data;
    },
    staleTime: 60_000,
  });
}

export function useBlogTags() {
  return useQuery<{ tag_type: string; tag_value: string; count: number }[]>({
    queryKey: ["blog-tags"],
    queryFn: async () => {
      const { data } = await api.get("/api/blog/tags");
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export function useBlogPost(postId: number | null) {
  return useQuery<BlogPostFull>({
    queryKey: ["blog-post", postId],
    queryFn: async () => {
      const { data } = await api.get(`/api/blog/posts/${postId}`);
      return data;
    },
    enabled: postId !== null,
    staleTime: 10 * 60_000,
  });
}

export function useAddBlogSource() {
  const qc = useQueryClient();
  return useMutation<BlogSource, Error, string>({
    mutationFn: async (url: string) => {
      const { data } = await api.post("/api/blog/sources", { url });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["blog-sources"] });
      qc.invalidateQueries({ queryKey: ["blog-feed"] });
    },
  });
}

export function useToggleBlogSource() {
  const qc = useQueryClient();
  return useMutation<BlogSource, Error, { id: number; is_active: boolean }>({
    mutationFn: async ({ id, is_active }) => {
      const { data } = await api.put(`/api/blog/sources/${id}/toggle`, { is_active });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["blog-sources"] });
      qc.invalidateQueries({ queryKey: ["blog-feed"] });
    },
  });
}
