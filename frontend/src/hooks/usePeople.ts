import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { FollowedPeopleWeek, PeopleDirectory, PeopleSort } from "@/types"

/** 인물 디렉토리 — 단일 집계(서버). 기본 7일 급상승 순, 언급 1건 롱테일은 tail=true일 때만 */
export function usePeopleDirectory({ days, sort, tail }: { days: number; sort: PeopleSort; tail: boolean }) {
  const qs = new URLSearchParams({ days: String(days), sort, min_mentions: tail ? "1" : "2" })
  return useQuery(apiQuery<PeopleDirectory>({ key: ["spine", "people", days, sort, tail], url: `/api/spine/person?${qs}`, staleTime: STALE.short, keepPrevious: true }))
}
/** 팔로우 인물의 이번 주 — 7일 언급·Δ·최신 문서(읽기 전용) */
export function useFollowedPeopleWeek() {
  return useQuery(apiQuery<FollowedPeopleWeek>({ key: ["spine", "people", "followed"], url: "/api/spine/person/followed", staleTime: STALE.medium }))
}
