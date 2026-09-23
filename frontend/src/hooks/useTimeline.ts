import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import { getJson, STALE } from '@/api/query'
import type { TimelineResponse, TimelineChannelsResponse } from '@/types'

export interface TimelineFilters {
  scope: string
  kind: string
  source: string
  page: number
  channel?: string
  until?: string
}

export function useTimeline(filters: TimelineFilters) {
  return useQuery({
    queryKey: ['spine', 'timeline', filters],
    queryFn: () => getJson<TimelineResponse>('/api/spine/feed/timeline', { ...filters, size: 20 }),
    staleTime: STALE.medium,
    // Filters must not briefly show posts from the previous, differently labelled lane.
  })
}


export function useTimelineChannels(until?: string) {
  return useQuery({
    queryKey: ['spine', 'timeline-channels', until],
    queryFn: () => getJson<TimelineChannelsResponse>('/api/spine/feed/channels', { until }),
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
