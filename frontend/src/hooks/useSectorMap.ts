import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { SectorPeers } from "@/types"

/** 섹터 → Peer 그룹 대응표 + 그룹별 섹터 비중·자동 제안 (GET, 모델 호출 없음) */
export function useSectorPeers() {
  return useQuery(apiQuery<SectorPeers>({ key: ["spine", "sector-map", "peers"], url: "/api/spine/sector-map/peers", staleTime: STALE.medium }))
}
