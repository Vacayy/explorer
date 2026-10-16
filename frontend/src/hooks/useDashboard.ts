import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import axios from "axios"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import type { LayoutEntry } from "@/components/widgets/layout"
import type { RiskResponse } from "@/types"

/** 지수 — IndexStrip과 같은 캐시 키(위젯과 전체 보기가 한 번만 받는다) */
export interface IndexRow { key: string; label: string; region: string; is_open: boolean; price: number | null; change_pct: number | null; spark: number[]; as_of: string | null }
export function useIndices() {
  return useQuery({
    ...apiQuery<{ as_of: string | null; items: IndexRow[]; degraded: string[]; any_open: boolean }>({ key: ["spine", "indices"], url: "/api/spine/indices", staleTime: STALE.medium }),
    refetchInterval: (q) => (q.state.data?.any_open ? 10 * 60_000 : 30 * 60_000),
    refetchIntervalInBackground: false,
  })
}

/** Risk 위젯 묶음 — 정본 계열(D-236)에서 3개월 창만 한 번에 (전 이력 1.4MB 대신 수 KB) */
export const RISK_WIDGET_KEYS = ["curve", "vix", "fear_greed", "hy"] as const
export function useRiskWindow() {
  return useQuery(apiQuery<RiskResponse>({
    key: ["spine", "risk", "window", "3m", RISK_WIDGET_KEYS.join(",")],
    url: `/api/spine/risk?range=3m&keys=${RISK_WIDGET_KEYS.join(",")}`, staleTime: STALE.short,
  }))
}

/** 대시보드 배치 — 서버 저장(docs/specs/home-widgets.md §4). 저장본이 없으면 null(기본 프리셋을 쓴다) */
export function useDashboardLayout(name = "home") {
  const qc = useQueryClient()
  const key = ["dashboard", "layout", name] as const
  const query = useQuery({
    queryKey: key,
    queryFn: async () => {
      try {
        return (await api.get<{ items: LayoutEntry[] }>(`/api/dashboard/layouts/${name}`)).data.items
      } catch (e) {
        if (axios.isAxiosError(e) && e.response?.status === 404) return null
        throw e
      }
    },
    staleTime: Infinity,
  })
  const save = useMutation({
    mutationFn: async (items: LayoutEntry[]) => (await api.put(`/api/dashboard/layouts/${name}`, { items: items.map(({ i, widget, x, y, w, h, params }) => ({ i, widget, x, y, w, h, params: params ?? {} })) })).data,
    onSuccess: (_d, items) => qc.setQueryData(key, items),
  })
  return { ...query, save }
}
