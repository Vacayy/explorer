import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { RetailPoint, RetailSnapshot, RetailSummary } from "@/types"

/** 개인 투자 열기(D-231) — 하루 1회 수집, 저장분 계산만. */
export function useRetailSummary() {
  return useQuery(apiQuery<RetailSummary>({ key: ["spine", "retail"], url: "/api/spine/retail", staleTime: STALE.long }))
}
export function useRetailHistory(days: number) {
  return useQuery(apiQuery<{ points: RetailPoint[] }>({ key: ["spine", "retail", "history", days], url: `/api/spine/retail/history?days=${days}`, staleTime: STALE.long }))
}
export function useRetailSnapshots() {
  return useQuery(apiQuery<RetailSnapshot[]>({ key: ["spine", "retail", "snapshots"], url: "/api/spine/retail/snapshots", staleTime: STALE.long }))
}
