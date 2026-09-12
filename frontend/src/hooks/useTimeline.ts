import { useQuery } from '@tanstack/react-query'
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
