import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import type { IndustryGroup, IndustryDetail, IndustryCandidate } from "@/types"

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

export function useCreateGroup() {
  const qc = useQueryClient()
  return useMutation<IndustryGroup, unknown, { name: string; description?: string }>({
    mutationFn: async (body) => {
      const { data } = await api.post("/api/industries/", body)
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["industry-groups"] }),
  })
}

export function useProposeMembers(groupId: number | null, enabled: boolean) {
  return useQuery<IndustryCandidate[]>({
    queryKey: ["industry-propose", groupId],
    queryFn: async () => {
      const { data } = await api.get(`/api/industries/${groupId}/propose`, {
        params: { limit: 30 },
      })
      return data
    },
    enabled: enabled && groupId !== null,
    staleTime: 0,
  })
}

export function useAddMember(groupId: number) {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, unknown, { stock_code: string; category: string }>({
    mutationFn: async (body) => {
      const { data } = await api.post(`/api/industries/${groupId}/members`, body)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["industry-detail", groupId] })
      qc.invalidateQueries({ queryKey: ["industry-groups"] })
    },
  })
}

export function useRemoveMember(groupId: number) {
  const qc = useQueryClient()
  return useMutation<{ ok: boolean }, unknown, number>({
    mutationFn: async (memberId) => {
      const { data } = await api.delete(`/api/industries/members/${memberId}`)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["industry-detail", groupId] })
      qc.invalidateQueries({ queryKey: ["industry-groups"] })
    },
  })
}
