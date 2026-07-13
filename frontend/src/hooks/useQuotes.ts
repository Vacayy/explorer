import { useQuery } from "@tanstack/react-query"
import { apiQuery } from "@/api/query"

/**
 * 실시간 시세 (네이버 폴링 프록시, BE 10초 캐시).
 * stock_prices(일 1회 종가)는 장중에 낡는다 — 현재가 표시는 이 훅이 담당.
 */
export interface LiveQuote {
  stock_code: string
  price: number | null
  change: number | null
  change_pct: number | null
  volume: number | null
  market_status: string | null
  traded_at: string | null
}

export function useQuotes(codes: string[]) {
  const key = [...new Set(codes)].sort().join(",")
  return useQuery({
    ...apiQuery<LiveQuote[]>({
      key: ["spine", "quotes", key],
      url: `/api/spine/quotes?codes=${encodeURIComponent(key)}`,
      staleTime: 8_000,
      enabled: key.length > 0,
    }),
    refetchInterval: 10_000,   // 장중 준실시간 (BE 10초 캐시와 짝)
  })
}

export function useQuote(code: string): LiveQuote | undefined {
  const { data } = useQuotes(code ? [code] : [])
  return data?.find((q) => q.stock_code === code)
}
