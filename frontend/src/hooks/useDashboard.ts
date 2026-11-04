import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { RiskResponse } from "@/types"

/** 지수 — 홈 지수 띠(market.indices) */
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
