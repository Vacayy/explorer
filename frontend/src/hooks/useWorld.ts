import { useMemo } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { rebuildResultMessage } from "@/lib/bigPicture"
import type { NarrativeItem } from "@/components/explore/NarrativeList"
import type { WorldBigPicture, WorldCheckpoint, WorldContested, WorldMyStocks, WorldNarrativeChanges, WorldRebuildResult } from "@/types"

/**
 * 월드모델 읽기 전용 훅 (docs/specs/world-model.md). 모두 /api/spine/world/* — 저장분만 읽고 생성하지 않는다.
 * 위젯과 '지금' 랜딩이 같은 키를 써서 한 번만 받는다.
 */
export function useBigPicture() {
  return useQuery(apiQuery<WorldBigPicture>({ key: ["spine", "world", "big-picture"], url: "/api/spine/world/big-picture", staleTime: STALE.medium }))
}

/** 이번 주 큰 그림 '다시 만들기' — 누를 때만 POST(서버가 6시간 쿨다운·주간 한도·입력 해시 가드, sonnet 1콜). 끝나면 큰 그림을 다시 읽는다 */
export function useBigPictureRebuild() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<WorldRebuildResult>("/api/spine/world/big-picture/rebuild", null, { timeout: 300_000 })).data,
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["spine", "world", "big-picture"] })
      const m = rebuildResultMessage(r)
      if (m.ok) toast.success(m.text)
      else toast.error(m.text)
    },
    onError: () => toast.error("큰 그림을 다시 만들지 못했습니다 · 이전 것을 그대로 둡니다"),
  })
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

/** 서사 목록(주제별 최신 버전) 색인 — 큰 그림 서사 칩의 버전·날짜, 상세 머리의 비중·급등 */
export function useNarrativeIndex(): Map<string, NarrativeItem> {
  const q = useQuery(apiQuery<{ items: NarrativeItem[] }>({ key: ["spine", "narrative", "list"], url: "/api/spine/narrative/list", staleTime: STALE.medium }))
  return useMemo(() => new Map((q.data?.items ?? []).map((n) => [n.topic, n])), [q.data])
}
