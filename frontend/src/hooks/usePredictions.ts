import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, postJson, STALE } from "@/api/query"
import type { KalshiDetail, KalshiPredictions } from "@/types"

/** Kalshi 예측시장 인기 이벤트 — 하루 세 번 수집한 마지막 묶음(홈 › 대시보드 캐러셀) */
export function usePredictions() {
  return useQuery(apiQuery<KalshiPredictions>({ key: ["spine", "home", "predictions"], url: "/api/spine/home/predictions", staleTime: STALE.long }))
}

/** 상세 창 — 결과 전부·규칙·결과별 일봉(서버가 Kalshi를 TTL 안에서 한 번 부른다) */
export function usePredictionDetail(eventTicker: string, range: string) {
  return useQuery({
    ...apiQuery<KalshiDetail>({ key: ["spine", "home", "predictions", eventTicker, range], url: `/api/spine/home/predictions/${encodeURIComponent(eventTicker)}?range=${range}`, staleTime: STALE.short }),
    enabled: !!eventTicker,
  })
}

/** 추적(핀) 켜기·끄기 — 켜면 인기순에서 빠져도 수집마다 따로 받아 맨 앞에 둔다 */
export function usePinPrediction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (v: { eventTicker: string; seriesTicker: string; pinned: boolean }) =>
      postJson<{ event_ticker: string; pinned: boolean }>(`/api/spine/home/predictions/${encodeURIComponent(v.eventTicker)}/pin`, { series_ticker: v.seriesTicker, pinned: v.pinned }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["spine", "home", "predictions"] }) },
  })
}
