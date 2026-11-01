import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { SectorMap } from "@/types"

/** 산업 맵 RS 사분면 — 18 대분류 현재·1~3주 전 궤적 (GET, 서버 15분 메모리 캐시·외부 호출 없음) */
export function useSectorMap() {
  return useQuery(apiQuery<SectorMap>({ key: ["spine", "sector-map"], url: "/api/spine/sector-map", staleTime: STALE.medium }))
}

export type Quadrant = "주도" | "부상" | "소외" | "과열·경계"

/** 사분면 — x=장기 RS, y=단기 RS, 50 기준 (SectorMapPage 라벨과 같은 규칙) */
export function quadrantOf(rsLong: number | null, rsShort: number | null): Quadrant | null {
  if (rsLong == null || rsShort == null) return null
  return rsLong >= 50 ? (rsShort >= 50 ? "주도" : "과열·경계") : (rsShort >= 50 ? "부상" : "소외")
}
