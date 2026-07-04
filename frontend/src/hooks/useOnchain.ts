import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"

export interface HyperliquidAsset {
  name: string
  markPx: number
  prevDayPx: number
  changePct: number
  funding: string
  openInterest: number
  dayNtlVlm: number
}

export interface HyperliquidStock {
  name: string
  midPx: number | null
  markPx: number | null
  changePct: number
  dayNtlVlm: number
}

export interface HyperliquidData {
  featured: HyperliquidAsset[]
  top_volume: HyperliquidAsset[]
  stocks: HyperliquidStock[]
}

export interface PolymarketMarket {
  question: string
  yesPrice: number | null
  volume: number
}

export interface PolymarketEvent {
  title: string
  slug: string
  volume: number
  markets: PolymarketMarket[]
}

export interface PolymarketCategory {
  label: string
  events: PolymarketEvent[]
}

export type PolymarketData = Record<string, PolymarketCategory>

export function useHyperliquid() {
  return useQuery<HyperliquidData>({
    queryKey: ["onchain", "hyperliquid"],
    queryFn: async () => {
      const { data } = await api.get("/api/onchain/hyperliquid")
      return data
    },
    staleTime: 30_000,
  })
}

export function usePolymarket() {
  return useQuery<PolymarketData>({
    queryKey: ["onchain", "polymarket"],
    queryFn: async () => {
      const { data } = await api.get("/api/onchain/polymarket")
      return data
    },
    staleTime: 60_000,
  })
}
