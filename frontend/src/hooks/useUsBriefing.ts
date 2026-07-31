import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { UsBriefing } from "@/types"

/** 어젯밤 미국장 브리핑 — 섹터 쏠림·개별 이슈 + 하루 1회 종합. status로 정상/경고/에러 구분. */
export function useUsBriefing() {
  return useQuery(apiQuery<UsBriefing>({
    key: ["spine", "us", "briefing"],
    url: "/api/spine/us/briefing",
    staleTime: STALE.medium,
  }))
}
