import { useEffect } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { shouldAutoCollect } from "@/lib/macroPage"
import type { BrkBenchKey, BrkRange, BrkResponse, EraCommentary, EraHeat, EraStateResponse, PricingResponse, RegimeCollectResponse, RegimesResponse, RiskResponse } from "@/types"

/** 국면 이력 — S&P500 국면·조정·10개월선·침체 (docs/specs/market-regimes.md) */
export function useRegimes() {
  return useQuery(apiQuery<RegimesResponse>({ key: ["spine", "regimes"], url: "/api/spine/regimes", staleTime: STALE.long }))
}

/** 버크셔 vs 지수 — 벤치·기간별 */
export function useBrk(bench: BrkBenchKey, range: BrkRange) {
  return useQuery(apiQuery<BrkResponse>({
    key: ["spine", "regimes", "brk", bench, range], url: `/api/spine/regimes/brk?bench=${bench}&range=${range}`,
    staleTime: STALE.long, keepPrevious: true,
  }))
}

/** 겹쳐 보기 — Risk 정본 계열(D-236)의 장기 이력을 그대로 쓴다 */
export const OVERLAY_KEYS = ["curve", "us10y", "us2y", "baa10y", "aaa10y"] as const
export type OverlayKey = typeof OVERLAY_KEYS[number]
export function useRegimeOverlay(key: OverlayKey) {
  return useQuery(apiQuery<RiskResponse>({
    key: ["spine", "risk", "window", "all", key], url: `/api/spine/risk?range=all&keys=${key}`, staleTime: STALE.long,
  }))
}

/** 시세·USREC 수집(처음엔 전 이력, 수십 초~수 분) — 자동 첫 수집과 관리자 '다시 받기'가 쓴다 */
export function useCollectRegimes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<RegimeCollectResponse>("/api/spine/regimes/collect", undefined, { timeout: 300_000 })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "regimes"] }),
  })
}

/** 지금 시장 읽기 — 네 층(규칙 판정) */
export function useEraState() {
  return useQuery(apiQuery<EraStateResponse>({ key: ["spine", "regimes", "state"], url: "/api/spine/regimes/state", staleTime: STALE.medium }))
}

/** LLM 해설 — 마지막 저장본 + 지금 입력과 다른지(stale) */
export function useEraCommentary() {
  return useQuery(apiQuery<EraCommentary>({ key: ["spine", "regimes", "commentary"], url: "/api/spine/regimes/commentary", staleTime: STALE.medium }))
}

/** 해설 만들기 — 입력이 같으면 서버가 저장본을 돌려준다(1~2분) */
export function useGenerateCommentary() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<EraCommentary>("/api/spine/regimes/commentary", undefined, { timeout: 360_000 })).data,
    onSuccess: data => qc.setQueryData(["spine", "regimes", "commentary"], data),
  })
}

/** Marks 온도 체크 정성 항목 기록 */
export function useSetEraCheck() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ key, state, note }: { key: string; state: EraHeat | null; note?: string | null }) =>
      (await api.put(`/api/spine/regimes/checks/${key}`, { state, note: note ?? null })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "regimes", "state"] }),
  })
}

/** 시장 프라이싱 원장 — 브리핑에서 이어 본 전제와 가격 지표 변화 */
export function usePricing(weeks = 8) {
  return useQuery(apiQuery<PricingResponse>({ key: ["spine", "pricing", weeks], url: `/api/spine/pricing?weeks=${weeks}`, staleTime: STALE.medium }))
}

/** 이번 페이지 수명에서 자동 첫 수집을 이미 시도했는지 — 탭을 오가며 다시 쏘지 않게 모듈 범위에 둔다 */
let autoCollectTried = false

/**
 * 국면 이력 자동 첫 수집(ia-redesign §4.28 결정 ①) — 지수 이력이 비어 있으면 사용자 버튼 없이 한 번만 받는다.
 * 다시 받기는 관리자 화면(작업·신선도)이 맡는다.
 */
export function useAutoCollectRegimes(q: { isSuccess: boolean; isFetching: boolean; data?: RegimesResponse }) {
  const collect = useCollectRegimes()
  const empty = !!q.data && q.data.phases.length === 0
  const { mutate, isPending } = collect
  useEffect(() => {
    if (!shouldAutoCollect({ loaded: q.isSuccess, empty, tried: autoCollectTried, pending: isPending })) return
    autoCollectTried = true
    mutate()
  }, [q.isSuccess, empty, isPending, mutate])
  return {
    collecting: isPending || (collect.isSuccess && empty && q.isFetching),
    failed: collect.isError || (collect.isSuccess && empty && !q.isFetching),
    error: collect.error,
    result: collect.data,
  }
}
