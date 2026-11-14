import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import type { IndustryGroup } from "@/types"

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
