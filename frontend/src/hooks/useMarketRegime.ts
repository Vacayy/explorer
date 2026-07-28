import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { MarketRegime } from "@/types"

/** 시장 국면 — 매크로 리스크 포스처 (D-076). EOD 갱신이라 short stale. */
export function useMarketRegime() {
  return useQuery(
    apiQuery<MarketRegime>({
      key: ["spine", "market-regime"],
      url: "/api/spine/market-regime",
      staleTime: STALE.short,
    }),
  )
}
