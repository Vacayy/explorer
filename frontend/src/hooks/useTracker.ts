import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import type { TrackerCondition, TrackerKind, TrackerRole, TrackerView } from "@/types"

/** 종목 추적 카드(docs/specs/stock-tracker.md) — 장중엔 5분마다 다시 읽는다(서버는 30분 점검 때 시세를 갱신) */
export function useTracker(code: string | null) {
  return useQuery({
    queryKey: ["spine", "tracker", code],
    queryFn: async () => (await api.get<TrackerView>(`/api/spine/tracker/${code}`)).data,
    enabled: !!code,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
}

/** 위젯을 막 놓았을 때 수급을 바로 받는다 */
export function prepareTracker(code: string) {
  return api.post(`/api/spine/tracker/${code}/prepare`).catch(() => undefined)
}

export function useTrackerConditionMutations(code: string) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ["spine", "tracker", code] })
  const add = useMutation({
    mutationFn: async (body: { role: TrackerRole; kind: TrackerKind; level?: number | null; ma?: number | null; label: string; note?: string | null }) =>
      (await api.post<TrackerCondition>(`/api/spine/tracker/${code}/conditions`, body)).data,
    onSuccess: refresh,
  })
  const patch = useMutation({
    mutationFn: async ({ id, ...body }: { id: number; done?: number }) => (await api.patch<TrackerCondition>(`/api/spine/tracker/conditions/${id}`, body)).data,
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/api/spine/tracker/conditions/${id}`)).data,
    onSuccess: refresh,
  })
  return { add, patch, remove }
}
