import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, postJson, STALE } from "@/api/query"
import { track } from "@/lib/usage"
import type { CallMomentum, CallReaction, ChainDetail, Expectation, KrSeasonOverview, RecentCall, SectorDetail, SeasonOverview, TranscriptCheck } from "@/types"

/** 실적 발언 모멘텀 — 컨콜 탭·모멘텀 띠·위젯 공용 (읽기 전용 GET, 판정은 매일 07:20) */
export function useCallMomentum() {
  return useQuery(apiQuery<CallMomentum>({ key: ["transcript", "momentum"], url: "/api/spine/transcript/momentum", staleTime: STALE.short }))
}

/** 최근 받은 컨콜 — 수집 시각순 */
export function useRecentCalls(days = 7) {
  return useQuery(apiQuery<RecentCall[]>({ key: ["transcript", "recent", days], url: "/api/spine/transcript/recent", params: { days }, staleTime: STALE.short }))
}

/** 저장된 컨콜 시장 반응 — 없으면 null. 생성은 useComputeCallReaction */
export function useCallReaction(transcriptId: number) {
  return useQuery(apiQuery<CallReaction | null>({ key: ["spine", "transcript", "reaction", transcriptId], url: `/api/spine/transcript/detail/${transcriptId}/reaction`, staleTime: STALE.medium }))
}

/** 시장 반응 정리 생성(sonnet, ~1분) — 재료가 그대로면 서버가 저장분을 즉답 */
export function useComputeCallReaction(transcriptId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => { track('action', 'reaction.make', { entity: transcriptId }); return postJson<CallReaction>(`/api/spine/transcript/detail/${transcriptId}/reaction`, null, { timeout: 300_000 }) },
    onSuccess: (d) => {
      qc.setQueryData(["spine", "transcript", "reaction", transcriptId], d)
      invalidateSeasonChain(qc)   // 반응 구조화 필드가 시즌·섹터·체인 화면에 들어간다
    },
  })
}

/** 이 종목의 가장 최근 실적 발표 조사 — SEC 8-K·yfinance 발표일 다시 읽기(AV 한도 무관) */
export function useCheckLatestCall() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => { track('action', 'transcript.check', { entity: ticker }); return postJson<TranscriptCheck>(`/api/spine/transcript/check/${ticker}`, null, { timeout: 120_000 }) },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "transcript", "follow"] }),
  })
}

/* ---------- 실적 시즌 체인 (docs/specs/earnings-season.md) ---------- */
const invalidateSeasonChain = (qc: ReturnType<typeof useQueryClient>) => {
  qc.invalidateQueries({ queryKey: ["spine", "transcript", "season"] })
  qc.invalidateQueries({ queryKey: ["spine", "transcript", "chain"] })
}

/** 실적 시즌 화면 — season 생략 시 지금 시즌 (읽기 전용, 매일 07:20 갱신) */
export function useSeason(season?: string | null) {
  return useQuery(apiQuery<SeasonOverview>({ key: ["spine", "transcript", "season", season ?? "current"], url: "/api/spine/transcript/season", params: season ? { season } : undefined, staleTime: STALE.short }))
}

/** 국내 실적 시즌 — 잠정실적 공시·DB 시세만(ia-redesign §4.22). 지난 시즌도 season으로 */
export function useKrSeason(season?: string | null) {
  return useQuery(apiQuery<KrSeasonOverview>({ key: ["spine", "transcript", "season", "kr", season ?? "current"], url: "/api/spine/transcript/season/kr", params: season ? { season } : undefined, staleTime: STALE.short }))
}

/** 섹터 상세 — 발표일 정렬 반응 경로·종목별·해석 이력·지난 시즌 비교 */
export function useSeasonSector(key: string, season?: string | null) {
  return useQuery(apiQuery<SectorDetail>({ key: ["spine", "transcript", "season", "sector", key, season ?? "current"], url: `/api/spine/transcript/season/sector/${encodeURIComponent(key)}`, params: season ? { season } : undefined, staleTime: STALE.short, keepPrevious: true }))
}

/** 콜 상세의 체인 — 발표 전 기대·반응 구조화·시계열·분기별 기록 */
export function useChain(transcriptId: number) {
  return useQuery(apiQuery<ChainDetail>({ key: ["spine", "transcript", "chain", transcriptId], url: `/api/spine/transcript/chain/${transcriptId}`, staleTime: STALE.short }))
}

/** 핵심 종목 직접 고정/해제 — 핵심이면 발표 전 기대·반응 정리가 자동으로 돈다 */
export function usePinCore() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { ticker: string; pinned: boolean }) => { track('action', v.pinned ? 'core.pin' : 'core.unpin', { entity: v.ticker }); return postJson<{ ticker: string; pinned: boolean }>("/api/spine/transcript/core/pin", v) },
    onSuccess: () => invalidateSeasonChain(qc),
  })
}

/** 다가오는 발표의 '발표 전 기대' 정리를 지금 만든다(sonnet, 1~2분) */
export function useMakeExpectation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { ticker: string; snapshot?: "d7" | "d1" }) => { track('action', 'expectation.make', { entity: v.ticker }); return postJson<Expectation>(`/api/spine/transcript/expectation/${v.ticker}`, null, { params: { snapshot: v.snapshot ?? "d7" }, timeout: 300_000 }) },
    onSuccess: () => invalidateSeasonChain(qc),
  })
}
