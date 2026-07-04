import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import type { IndustryGroup, IndustryDetail } from "@/types"

export function useIndustryGroups() {
  return useQuery<IndustryGroup[]>({
    queryKey: ["industry-groups"],
    queryFn: async () => {
      const { data } = await api.get("/api/industries/")
      return data
    },
    staleTime: Infinity,
  })
}

export function useIndustryDetail(groupId: number | null) {
  return useQuery<IndustryDetail>({
    queryKey: ["industry-detail", groupId],
    queryFn: async () => {
      const { data } = await api.get(`/api/industries/${groupId}`)
      return data
    },
    enabled: groupId !== null,
    staleTime: 5 * 60_000,
  })
}

export function useFetchIndustryPrices(groupId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post(`/api/industries/${groupId}/fetch-prices`)
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["industry-detail", groupId] }),
  })
}
