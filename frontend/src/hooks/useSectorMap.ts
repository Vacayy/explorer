import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { SectorMap, SectorPeers } from "@/types"

/** 산업 맵 RS 사분면 — 18 대분류 현재·1~3주 전 궤적 (GET, 서버 15분 메모리 캐시·외부 호출 없음) */
export function useSectorMap() {
  return useQuery(apiQuery<SectorMap>({ key: ["spine", "sector-map"], url: "/api/spine/sector-map", staleTime: STALE.medium }))
}

/** 섹터 → Peer 그룹 대응표 + 그룹별 섹터 비중·자동 제안 (GET, 모델 호출 없음) */
export function useSectorPeers() {
  return useQuery(apiQuery<SectorPeers>({ key: ["spine", "sector-map", "peers"], url: "/api/spine/sector-map/peers", staleTime: STALE.medium }))
}

export type Quadrant = "주도" | "부상" | "소외" | "과열·경계"

