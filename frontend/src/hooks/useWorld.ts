import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { WorldBigPicture, WorldCheckpoint, WorldContested, WorldMyStocks, WorldNarrativeChanges } from "@/types"

/**
 * 월드모델 읽기 전용 훅 (docs/specs/world-model.md). 모두 /api/spine/world/* — 저장분만 읽고 생성하지 않는다.
 * 위젯과 '지금' 랜딩이 같은 키를 써서 한 번만 받는다.
 */
export function useBigPicture() {
  return useQuery(apiQuery<WorldBigPicture>({ key: ["spine", "world", "big-picture"], url: "/api/spine/world/big-picture", staleTime: STALE.medium }))
}

export function useNarrativeChanges(days = 7) {
  return useQuery(apiQuery<WorldNarrativeChanges>({
    key: ["spine", "world", "changes", days], url: "/api/spine/world/changes", params: { days }, staleTime: STALE.medium,
  }))
}

export function useContestedPremises() {
  return useQuery(apiQuery<WorldContested>({ key: ["spine", "world", "contested"], url: "/api/spine/world/contested", staleTime: STALE.medium }))
}

export function useMyStockNarratives() {
  return useQuery(apiQuery<WorldMyStocks>({ key: ["spine", "world", "my-stocks"], url: "/api/spine/world/my-stocks", staleTime: STALE.medium }))
}

/**
 * 저장된 서사가 있는 주제 집합 — 서사 목록과 같은 캐시 키. 서사가 없는 주제로 링크하면
 * 상세가 생성을 자동 요청하므로, 링크를 걸기 전에 이 집합으로 확인한다.
 */
export function useNarrativeTopics() {
  const q = useQuery(apiQuery<{ items: { topic: string }[] }>({
    key: ["spine", "narrative", "list"], url: "/api/spine/narrative/list", staleTime: STALE.medium,
  }))
  return { ...q, topics: new Set((q.data?.items ?? []).map(i => i.topic)) }
}

export function useNarrativeCheckpoint(topic: string) {
  return useQuery(apiQuery<WorldCheckpoint>({
    key: ["spine", "world", "checkpoint", topic], url: "/api/spine/world/checkpoint", params: { topic },
    staleTime: STALE.short, enabled: !!topic,
  }))
}
