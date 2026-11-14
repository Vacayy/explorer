import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { MarketKey, MarketOverview } from "@/types"

/** 홈 › 한국·미국 시장 ① 지수 차트 + 요약 지표 (D-325) — 저장분만 읽는 API. 장중 경로는 10분마다 쌓이므로 5분마다 다시 읽는다 */
export function useMarketOverview(market: MarketKey) {
  return useQuery({
    ...apiQuery<MarketOverview>({ key: ["spine", "market", market, "overview"], url: `/api/spine/market/${market}/overview`, staleTime: STALE.short }),
    refetchInterval: 5 * 60_000,
  })
}
