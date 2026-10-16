import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { spineKeys } from "@/api/spine"

export type RefreshKind = "telegram" | "youtube" | "blog"
export interface RefreshState {
  kind: RefreshKind; key: string
  status: "idle" | "running" | "done" | "skipped" | "error"
  started_at: string | null; finished_at: string | null
  stats: { refs: number; docs: number; new: number; updated: number; unchanged: number; source: string } | null
  error: string | null
  already_running?: boolean
}

const NOUN: Record<RefreshKind, string> = { telegram: "글", youtube: "영상", blog: "글" }

/** 소스 하나 '지금 수집' (D-199) — POST로 시작하고 끝날 때까지 2초마다 상태를 본다. 끝나면 결과를 토스트로 알리고 소스·피드 쿼리를 새로 읽는다. */
export function useRefreshSource() {
  const qc = useQueryClient()
  const [active, setActive] = useState<{ kind: RefreshKind; key: string; name: string } | null>(null)
  const start = useMutation({
    mutationFn: async (v: { kind: RefreshKind; key: string; name: string }) =>
      (await api.post<RefreshState>("/api/spine/sources/refresh", { kind: v.kind, key: v.key })).data,
    onSuccess: (state, v) => {
      setActive(v)
      if (state.already_running) toast.message(`${v.name} 수집이 이미 진행 중입니다`)
    },
    onError: (e: unknown, v) =>
      toast.error(`${v.name} 수집을 시작하지 못했습니다`, { description: (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail }),
  })
  const poll = useQuery({
    queryKey: ["spine", "sources", "refresh", active?.kind, active?.key],
    queryFn: async () => (await api.get<RefreshState>("/api/spine/sources/refresh", { params: { kind: active!.kind, key: active!.key } })).data,
    enabled: !!active,
    refetchInterval: query => (query.state.data?.status === "running" || !query.state.data ? 2000 : false),
  })
  const state = poll.data
  useEffect(() => {
    if (!active || !state || state.status === "running" || state.status === "idle") return
    const noun = NOUN[active.kind]
    if (state.status === "done" && state.stats) {
      const { new: added, updated, unchanged } = state.stats
      toast.success(`${active.name}: 새 ${noun} ${added}개 · 갱신 ${updated}개`, {
        description: added + updated === 0 ? `변화 없음 ${unchanged}개. 원본에 새 ${noun}이 없거나 아직 공개 미리보기에 오르지 않았습니다.` : `변화 없음 ${unchanged}개. 새 ${noun}은 태깅까지 끝나 피드·타임라인에 바로 보입니다.`,
      })
    } else if (state.status === "skipped") {
      toast.warning(`${active.name}: 수집을 건너뛰었습니다`, { description: state.error ?? undefined })
    } else if (state.status === "error") {
      toast.error(`${active.name}: 수집 실패`, { description: state.error ?? undefined })
    }
    try {
      qc.invalidateQueries({ queryKey: ["spine", "sources", "health"] })
      qc.invalidateQueries({ queryKey: ["telegram-channels"] })
      qc.invalidateQueries({ queryKey: ["youtube-channels"] })
      qc.invalidateQueries({ queryKey: ["blog-sources"] })
      qc.invalidateQueries({ queryKey: ["spine", "timeline"] })
      qc.invalidateQueries({ queryKey: ["spine", "timeline-channels"] })
      qc.invalidateQueries({ queryKey: spineKeys.sourceDossier(active.kind, active.key) })
    } finally {
      setActive(null)
    }
  }, [state, active, qc])
  return {
    refresh: (kind: RefreshKind, key: string, name: string) => start.mutate({ kind, key, name }),
    isRefreshing: (kind: RefreshKind, key: string) => !!active && active.kind === kind && active.key === key,
  }
}
