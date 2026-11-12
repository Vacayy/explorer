import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { KalshiPredictions } from "@/types"

/** Kalshi 예측시장 인기 이벤트 — 하루 세 번 수집한 마지막 묶음(홈 › 대시보드 캐러셀) */
export function usePredictions() {
  return useQuery(apiQuery<KalshiPredictions>({ key: ["spine", "home", "predictions"], url: "/api/spine/home/predictions", staleTime: STALE.long }))
}
