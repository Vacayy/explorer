import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, postJson, STALE, toApiError } from "@/api/query"
import type { HoldingFlow, HoldingThesis, PortfolioEvent, PortfolioExposure, PortfolioHistoryPoint, PortfolioSummary, PortfolioTransaction, PortfolioTxInput } from "@/types"

const KEY = ["portfolio"] as const

const LIVE_POLL = 30 * 60_000   // 서버 시세 TTL과 같은 30분. 백그라운드 탭에서는 폴링하지 않는다.

/** 장중 시세를 쓰는 종목이 있으면 30분마다 다시 조회(서버가 30분 지난 시세만 새로 받아온다). */
export function usePortfolio() {
  return useQuery({
    ...apiQuery<PortfolioSummary>({ key: [...KEY, "summary"], url: "/api/portfolio", staleTime: STALE.short }),
    refetchInterval: query => query.state.data?.quoted_at ? LIVE_POLL : false,
  })
}
export function usePortfolioHistory(live = false) {
  return useQuery({
    ...apiQuery<PortfolioHistoryPoint[]>({ key: [...KEY, "history"], url: "/api/portfolio/history", staleTime: STALE.short }),
    refetchInterval: live ? LIVE_POLL : false,
  })
}
/** 공통 변수 — 보유 종목이 함께 기대는 변수(그래프·동시 언급·밸류체인). 거래가 바뀌면 ["portfolio"] 무효화로 다시 계산. */
export function usePortfolioExposure() {
  return useQuery(apiQuery<PortfolioExposure>({ key: [...KEY, "exposure"], url: "/api/portfolio/exposure", staleTime: STALE.long }))
}
/** 다가오는 이벤트 — 확정(DART)·예상·관련 해외 실적일. 수집은 매일 16:50. */
export function usePortfolioEvents(days = 45) {
  return useQuery(apiQuery<PortfolioEvent[]>({ key: [...KEY, "events", days], url: "/api/portfolio/events", params: { days }, staleTime: STALE.long }))
}
/** 자료 흐름 — 보유 종목별 14일 언급·논조와 최신 1D 요약. */
export function usePortfolioFlow() {
  return useQuery(apiQuery<HoldingFlow[]>({ key: [...KEY, "flow"], url: "/api/portfolio/flow", staleTime: STALE.short }))
}
/** 보유 종목 논지(핵심질문 추적기) — 종목코드별. */
export function usePortfolioTheses() {
  return useQuery(apiQuery<Record<string, HoldingThesis>>({ key: [...KEY, "thesis"], url: "/api/portfolio/thesis", staleTime: STALE.short }))
}
/** 논지 감시 시작 — 서버가 sonnet 1회로 분해(1~3분). */
export function useStartThesis() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { stock_code: string; why: string; falsifier: string }) =>
      postJson<{ id: number }>("/api/portfolio/thesis", body, { timeout: 300_000 }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY, "thesis"] }),
  })
}
export function usePortfolioTransactions(enabled = true) {
  return useQuery(apiQuery<PortfolioTransaction[]>({ key: [...KEY, "transactions"], url: "/api/portfolio/transactions", enabled }))
}
export function useAddPortfolioTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PortfolioTxInput) => postJson<{ ok: boolean; id: number }>("/api/portfolio/transactions", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
/** '시세 갱신' 버튼 — 보유 종목 실시간 시세를 지금 받고 화면 전체를 다시 계산한다. */
export function useRefreshPortfolioQuotes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => postJson<{ quoted_at: string | null; count: number }>("/api/portfolio/quotes/refresh"),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
export function useDeletePortfolioTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      try { await api.delete(`/api/portfolio/transactions/${id}`) } catch (e) { throw toApiError(e) }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
