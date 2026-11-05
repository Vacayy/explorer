import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import type { AdminHealthItem, AdminJobRun, AdminJobStatus, CurationLog } from "@/types"

/** 관리자 › 작업·신선도 (ia-redesign §4.31) — 작업 목록·켜짐 */
export function useAdminJobs() {
  return useQuery(apiQuery<AdminJobStatus[]>({ key: ["spine", "admin", "jobs"], url: "/api/spine/admin/jobs", staleTime: STALE.short }))
}

/** 최근 실행 내역 */
export function useAdminRuns(limit = 40) {
  return useQuery(apiQuery<AdminJobRun[]>({ key: ["spine", "admin", "runs", limit], url: `/api/spine/admin/runs?limit=${limit}`, staleTime: STALE.short }))
}

/** 데이터 신선도(D-222) — 상단 바 운영 상태와 같은 키 */
export function useAdminHealth() {
  return useQuery(apiQuery<AdminHealthItem[]>({ key: ["spine", "admin", "health"], url: "/api/spine/admin/health", staleTime: STALE.short }))
}

/** 자동 정리 판정 기록(D-294) — 종류·판정 필터는 서버에서 */
export function useCurationLog(kind: string | null, verdict: string | null) {
  const params = new URLSearchParams({ limit: "1000" })
  if (kind) params.set("kind", kind)
  if (verdict) params.set("verdict", verdict)
  return useQuery(apiQuery<CurationLog>({
    key: ["spine", "curation", kind ?? "", verdict ?? ""], url: `/api/spine/curation?${params}`, staleTime: STALE.short, keepPrevious: true,
  }))
}

/** 작업·플래그 켜고 끄기 — 누를 때만(POST /api/spine/admin/flag) */
export function useSetFlag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (b: { name: string; enabled: boolean }) => (await api.post("/api/spine/admin/flag", b)).data,
    onSuccess: (_d, b) => {
      toast.success(`${b.name} ${b.enabled ? "켰습니다" : "껐습니다"}`)
      void qc.invalidateQueries({ queryKey: ["spine", "admin", "jobs"] })
      void qc.invalidateQueries({ queryKey: ["spine", "curation"] })
    },
    onError: () => toast.error("설정을 바꾸지 못했습니다. 다시 시도해 주세요."),
  })
}
