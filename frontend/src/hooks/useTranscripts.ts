import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { CallMomentum, RecentCall } from "@/types"

/** 실적 발언 모멘텀 — 컨콜 탭·모멘텀 띠·위젯 공용 (읽기 전용 GET, 판정은 매일 07:20) */
export function useCallMomentum() {
  return useQuery(apiQuery<CallMomentum>({ key: ["transcript", "momentum"], url: "/api/spine/transcript/momentum", staleTime: STALE.short }))
}

/** 최근 받은 컨콜 — 수집 시각순 */
export function useRecentCalls(days = 7) {
  return useQuery(apiQuery<RecentCall[]>({ key: ["transcript", "recent", days], url: "/api/spine/transcript/recent", params: { days }, staleTime: STALE.short }))
}
