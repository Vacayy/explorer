import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import type { BrkBenchKey, BrkRange, BrkResponse, RegimeCollectResponse, RegimesResponse, RiskResponse } from "@/types"

/** 국면 이력 — S&P500 국면·조정·10개월선·침체 (docs/specs/market-regimes.md) */
export function useRegimes() {
  return useQuery(apiQuery<RegimesResponse>({ key: ["spine", "regimes"], url: "/api/spine/regimes", staleTime: STALE.long }))
}

/** 버크셔 vs 지수 — 벤치·기간별 */
export function useBrk(bench: BrkBenchKey, range: BrkRange) {
  return useQuery(apiQuery<BrkResponse>({
    key: ["spine", "regimes", "brk", bench, range], url: `/api/spine/regimes/brk?bench=${bench}&range=${range}`,
    staleTime: STALE.long, keepPrevious: true,
  }))
}

/** 겹쳐 보기 — Risk 정본 계열(D-236)의 장기 이력을 그대로 쓴다 */
export const OVERLAY_KEYS = ["curve", "us10y", "us2y", "baa10y", "aaa10y"] as const
export type OverlayKey = typeof OVERLAY_KEYS[number]
export function useRegimeOverlay(key: OverlayKey) {
  return useQuery(apiQuery<RiskResponse>({
    key: ["spine", "risk", "window", "all", key], url: `/api/spine/risk?range=all&keys=${key}`, staleTime: STALE.long,
  }))
}

/** 시세·USREC 수집(처음엔 전 이력) */
export function useCollectRegimes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<RegimeCollectResponse>("/api/spine/regimes/collect")).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "regimes"] }),
  })
}
