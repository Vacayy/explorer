import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { IndustryMap, IndustrySectorDetail, SectorPeerList, UsIndustryMap, UsSectorDetail, UsSectorMarket } from "@/types"

/** 섹터 지도 — 섹터마다 대표지수·RS·61거래일 선 (GET, 저장분만 · 서버 15분 메모리 캐시) */
export function useIndustryMap() {
  return useQuery(apiQuery<IndustryMap>({ key: ["spine", "industry", "map"], url: "/api/spine/industry/map", staleTime: STALE.medium }))
}

/** 섹터 화면 머리·개요·종목 (GET, 저장분만) */
export function useSectorDetail(sector: string) {
  return useQuery(apiQuery<IndustrySectorDetail>({ key: ["spine", "industry", sector], url: `/api/spine/industry/${encodeURIComponent(sector)}`, staleTime: STALE.medium, enabled: !!sector }))
}

/** 섹터의 하위 Peer 그룹 — 종목 수·20·60거래일 중앙값 (GET) */
export function useSectorPeerList(sector: string) {
  return useQuery(apiQuery<SectorPeerList>({ key: ["spine", "industry", sector, "peers"], url: `/api/spine/industry/${encodeURIComponent(sector)}/peers`, staleTime: STALE.medium, enabled: !!sector }))
}

/** 팔로우 중인 엔티티 (GET /api/spine/follows) — 섹터 머리 팔로우 상태 */
export function useFollowedEntities() {
  return useQuery(apiQuery<{ entity_id: number }[]>({ key: ["spine", "follows"], url: "/api/spine/follows", staleTime: STALE.short }))
}

/** 미국 섹터 지도 — GICS 11 + 세부 업종 13 ETF의 RS·수익률·61거래일 선 (GET, 저장분만, §4.36) */
export function useUsIndustryMap(enabled = true) {
  return useQuery(apiQuery<UsIndustryMap>({ key: ["spine", "industry", "us", "map"], url: "/api/spine/industry/us/map", staleTime: STALE.medium, enabled }))
}

/** 미국 섹터 화면 — ETF 머리·ETF vs SPY·같은 상위 안 비교·내 커버리지·주요 자료·데이터 연결 (GET, 저장분만) */
export function useUsSectorDetail(ticker: string) {
  return useQuery(apiQuery<UsSectorDetail>({ key: ["spine", "industry", "us", ticker], url: `/api/spine/industry/us/${encodeURIComponent(ticker)}`, staleTime: STALE.medium, enabled: !!ticker }))
}

/** Public ETF-only detail; never falls back to the personal detail endpoint. */
export function useUsSectorMarket(ticker: string) {
  return useQuery(apiQuery<UsSectorMarket>({ key: ["public", "industry", "us", ticker], url: `/api/spine/industry/us/${encodeURIComponent(ticker)}/market`, staleTime: STALE.medium, enabled: !!ticker }))
}
