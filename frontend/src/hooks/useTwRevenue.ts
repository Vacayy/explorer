import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { KrConfirm, PropagationResponse, TwLinksResponse, TwRevenueResponse, ValueChainResponse } from "@/types"

/** 대만 월매출 92개사 — 저장분 읽기(수집은 매일 11:00 launchd twrevenue) */
export function useTwRevenue() {
  return useQuery(apiQuery<TwRevenueResponse>({ key: ["spine", "tw", "revenue"], url: "/api/spine/tw/revenue", staleTime: STALE.long }))
}

/** 대만 → 한국 연결 신호 — kr를 주면 그 종목 연결만 */
export function useTwLinks(kr?: string) {
  return useQuery(apiQuery<TwLinksResponse>({
    key: ["spine", "tw", "links", kr ?? "all"], url: "/api/spine/tw/links", params: kr ? { kr } : undefined, staleTime: STALE.long,
  }))
}

/** 한국 확인 신호 — 대만·수출·공시 세 원천 방향. kr를 주면 그 종목만 */
export function useKrConfirm(kr?: string) {
  return useQuery(apiQuery<KrConfirm[]>({
    key: ["spine", "tw", "confirm", kr ?? "all"], url: "/api/spine/tw/confirm", params: kr ? { kr } : undefined, staleTime: STALE.long,
  }))
}

/** 밸류체인 지도(노드 신호·엣지 시차)와 번지는 중 판정 */
export function useValueChain() {
  return useQuery(apiQuery<ValueChainResponse>({ key: ["spine", "tw", "value-chain"], url: "/api/spine/tw/value-chain", staleTime: STALE.long }))
}
export function usePropagation() {
  return useQuery(apiQuery<PropagationResponse>({ key: ["spine", "tw", "propagation"], url: "/api/spine/tw/propagation", staleTime: STALE.long }))
}
