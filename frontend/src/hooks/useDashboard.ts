import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { KrBreadth, RiskResponse } from "@/types"

/** 지수 — 홈 지수 띠(market.indices) */
export interface IndexRow { key: string; label: string; region: string; is_open: boolean; price: number | null; change_pct: number | null; spark: number[]; as_of: string | null; fetched_at: string | null }
export function useIndices() {
  return useQuery({
    ...apiQuery<{ as_of: string | null; items: IndexRow[]; degraded: string[]; any_open: boolean }>({ key: ["spine", "indices"], url: "/api/spine/indices", staleTime: STALE.medium }),
    // 서버는 장중 정기 수집 봉(10분)을 얹고 휴장 TTL을 다음 개장 전에 끊는다 — 화면도 장중 5분·휴장 10분으로 따라간다(장전 값에 30분 넘게 머물던 문제)
    refetchInterval: (q) => (q.state.data?.any_open ? 5 * 60_000 : 10 * 60_000),
    refetchIntervalInBackground: false,
  })
}

/** 국내 시장 폭(D-321) — 최근 거래일 상승·하락 종목 수. 홈 기상도 색 비율 */
export function useKrBreadth() {
  return useQuery(apiQuery<KrBreadth | null>({ key: ["spine", "indices", "breadth"], url: "/api/spine/indices/breadth", staleTime: STALE.long }))
}

/** Risk 위젯 묶음 — 정본 계열(D-236)에서 3개월 창만 한 번에 (전 이력 1.4MB 대신 수 KB) */
export const RISK_WIDGET_KEYS = ["curve", "vix", "fear_greed", "hy"] as const
export function useRiskWindow() {
  return useQuery(apiQuery<RiskResponse>({
    key: ["spine", "risk", "window", "3m", RISK_WIDGET_KEYS.join(",")],
    url: `/api/spine/risk?range=3m&keys=${RISK_WIDGET_KEYS.join(",")}`, staleTime: STALE.short,
  }))
}
