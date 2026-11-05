import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { FollowedPeopleWeek, PeopleDirectory, PeopleHome, PeopleSort, PersonDetail, PersonResolve } from "@/types"

/** 인물 디렉토리 — 단일 집계(서버). 기본 7일 급상승 순, 언급 1건 롱테일은 tail=true일 때만 */
export function usePeopleDirectory({ days, sort, tail }: { days: number; sort: PeopleSort; tail: boolean }) {
  const qs = new URLSearchParams({ days: String(days), sort, min_mentions: tail ? "1" : "2" })
  return useQuery(apiQuery<PeopleDirectory>({ key: ["spine", "people", days, sort, tail], url: `/api/spine/person?${qs}`, staleTime: STALE.short, keepPrevious: true }))
}
/** 팔로우 인물의 이번 주 — 7일 언급·Δ·최신 문서(읽기 전용) */
export function useFollowedPeopleWeek() {
  return useQuery(apiQuery<FollowedPeopleWeek>({ key: ["spine", "people", "followed"], url: "/api/spine/person/followed", staleTime: STALE.medium }))
}

/** 인물 홈(ia-redesign §4.23 A) — 팔로우·기록이 있는 인물·이번 주 언급이 는 인물. 묶은 이름은 한 사람 */
export function usePeopleHome() {
  return useQuery(apiQuery<PeopleHome>({ key: ["spine", "people", "home"], url: "/api/spine/person/home", staleTime: STALE.short }))
}
/** 인물 상세(id) — 묶인 이름의 id면 대표 인물로 온다(entity_id ≠ requested_id) */
export function usePersonDetail(id: number) {
  return useQuery(apiQuery<PersonDetail>({ key: ["spine", "person", "id", id], url: `/api/spine/person/${id}`, staleTime: STALE.short, enabled: Number.isFinite(id) && id > 0 }))
}
/** 옛 이름 주소(/person?name=) → 대표 인물 id */
export function usePersonResolve(name: string) {
  return useQuery(apiQuery<PersonResolve>({ key: ["spine", "person", "resolve", name], url: `/api/spine/person/resolve?${new URLSearchParams({ name })}`, staleTime: STALE.medium, enabled: !!name }))
}
