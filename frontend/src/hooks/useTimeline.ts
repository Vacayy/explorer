import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import { getJson, STALE, ApiError, toApiError } from '@/api/query'
import type { AiActivityItem, MarkAllReadPlatform, MarkAllReadResponse, TimelineResponse, TimelineChannelsResponse } from '@/types'

export interface TimelineFilters {
  scope: string
  kind: string
  source: string
  page: number
  channel?: string
  topic?: string   // 주제 칩 (D-208)
  until?: string
  generation?: string
}

export function useTimeline(filters: TimelineFilters) {
  return useQuery({
    queryKey: ['spine', 'timeline', filters],
    queryFn: async () => {
      const response = await api.get<TimelineResponse>('/api/spine/feed/timeline', { params: { ...filters, size: 20 } })
      const data = response.data
      if (filters.generation && data.generation !== filters.generation) throw new ApiError('조회하던 자료가 갱신됐습니다.', 410)
      const media = response.headers['x-explorer-media-generation']
      return { ...data, _mediaGeneration: data.generation && media === data.generation ? data.generation : undefined }
    },
    staleTime: STALE.medium,
    // Filters must not briefly show posts from the previous, differently labelled lane.
  })
}

/** 상단 바 'AI가 최근 만든 것'(D-325) — Explorer 산출물(기업 요약·컨콜·내러티브·리포트·파급 분석·수출입) 최신 20건. 피드의 Explorer 묶음과 같은 원천 */
export function useExplorerOutputs() {
  return useQuery({
    queryKey: ['spine', 'timeline', 'explorer-outputs'],
    queryFn: () => getJson<TimelineResponse>('/api/spine/feed/timeline', { scope: 'system', kind: 'all', source: 'all', page: 1, size: 20 }),
    staleTime: STALE.medium,
  })
}

/** 'AI가 최근 만든 것'의 다른 원천 — 지난 7일 AI 산출물(유튜브 AI 정리본 포함, 타임라인에 없는 종류). GET /api/spine/home/ai-activity */
export function useAiActivity() {
  return useQuery({
    queryKey: ['spine', 'home', 'ai-activity'],
    queryFn: () => getJson<AiActivityItem[]>('/api/spine/home/ai-activity', { days: 7, limit: 60 }),
    staleTime: STALE.medium,
  })
}

export function useTimelineChannels(until?: string, generation?: string, enabled = true) {
  return useQuery({
    queryKey: ['spine', 'timeline-channels', until, generation],
    queryFn: async () => {
      try {
        const result = await api.get<TimelineChannelsResponse>('/api/spine/feed/channels', { params: { until, generation } })
        if (generation && result.headers['x-explorer-generation'] !== generation) throw new ApiError('조회하던 자료가 갱신됐습니다.', 410)
        return result.data
      } catch (error) { throw toApiError(error) }
    },
    enabled,
    staleTime: STALE.medium,
  })
}

/** 소스를 read_until까지 읽음으로 표시 (D-200). 소스를 열어 게시물이 보이면 호출한다. 문서 코퍼스에는 쓰지 않는다. */
export function useMarkChannelRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { channel: string; read_until: string }) =>
      (await api.post<{ channel: string; read_until: string }>('/api/spine/feed/channels/read', v)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['spine', 'timeline-channels'] }),
  })
}

/** 피드 '모두 읽음'(D-301) — 지금 칩 범위의 소스를 read_until(보고 있는 목록의 기준 시각)까지 한 번에 읽음으로 */
export function useMarkAllRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { platform: MarkAllReadPlatform; read_until: string }) =>
      (await api.post<MarkAllReadResponse>('/api/spine/feed/channels/read-all', v)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['spine', 'timeline-channels'] }),
  })
}
