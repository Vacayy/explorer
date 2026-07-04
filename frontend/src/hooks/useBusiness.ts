import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/api/client";
import type { BusinessSegment } from "@/types";

export function useBusinessSegments(stockCode: string, segmentType: string = "division", years: number = 5) {
  return useQuery<{ items: BusinessSegment[] }>({
    queryKey: ["business-segments", stockCode, segmentType, years],
    queryFn: async () => {
      const { data } = await api.get(`/api/business/${stockCode}/segments`, {
        params: { segment_type: segmentType, years },
      });
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export function useCreateSegment(stockCode: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      bsns_year: number;
      segment_type: string;
      segment_name: string;
      revenue?: number;
      ratio?: number;
    }) => {
      const { data } = await api.post(`/api/business/${stockCode}/segments`, body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["business-segments", stockCode] }),
  });
}

export function useDeleteSegment(stockCode: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/business/segments/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["business-segments", stockCode] }),
  });
}
