import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import type { ChainPreview, ChainReport, ChainReportItem, ExpectationsResponse, FlowResponse, KrConfirm, PropagationResponse, TwLinksResponse, TwRevenueResponse, ValueChainResponse } from "@/types"

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

/** 돈의 흐름 — 흐름 크기 상위·스포트라이트 가설·의심받는 칸·식는 칸 */
export function useValueChainFlow() {
  return useQuery(apiQuery<FlowResponse>({ key: ["spine", "tw", "flow"], url: "/api/spine/tw/flow", staleTime: STALE.long }))
}

/** 시장 기대치 — 칸 구성 회사 컨센서스·리서치 전망, 관측과 나란히(docs/specs/value-chain.md §15) */
export function useValueChainExpectations() {
  return useQuery(apiQuery<ExpectationsResponse>({ key: ["spine", "tw", "expectations"], url: "/api/spine/tw/expectations", staleTime: STALE.long }))
}

/** 트리 보고서(§16) — 생성 전 트리 미리보기(LLM 0) */
export function useChainPreview(root: string | null) {
  return useQuery(apiQuery<ChainPreview>({ key: ["spine", "tw", "chain-preview", root], url: "/api/spine/tw/chain-report/preview",
    params: { root }, enabled: !!root, staleTime: STALE.long }))
}

/** 루트별 보고서 이력(최신순) */
export function useChainReports(root: string | null) {
  return useQuery(apiQuery<ChainReportItem[]>({ key: ["spine", "tw", "chain-reports", root], url: "/api/spine/tw/chain-reports", params: { root }, enabled: !!root }))
}

/** 보고서 한 편 — 생성 중이면 4초마다 다시 읽는다 */
export function useChainReport(id: number | null) {
  return useQuery({
    queryKey: ["spine", "tw", "chain-report", id],
    queryFn: async () => (await api.get<ChainReport>(`/api/spine/tw/chain-report/${id}`)).data,
    enabled: id != null,
    refetchInterval: q => (q.state.data?.status === "running" ? 4000 : false),
  })
}

/** 보고서 만들기 — 버튼으로 요청할 때만(비싼 생성은 승인 뒤로) */
export function useCreateChainReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (root: string) => (await api.post<ChainReport>("/api/spine/tw/chain-report", null, { params: { root } })).data,
    onSuccess: r => { void qc.invalidateQueries({ queryKey: ["spine", "tw", "chain-reports", r.root] }) },
  })
}
