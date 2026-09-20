import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '@/api/client'
import type { DiscoveryCase, DiscoveryRecommendation, SavedStrategy } from '@/components/analysis/discoveryTypes'

const ROOT = `${API_BASE}/api/analysis/discovery`
const key = ['market-discovery'] as const

export async function discoveryRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw Object.assign(new Error(typeof error?.detail === 'string' ? error.detail : `요청을 처리하지 못했습니다 (${response.status}).`), { status: response.status })
  }
  return response.json() as Promise<T>
}

/** Network retries retain the request key; a successful deliberate repeat gets a new key. */
export function useDiscoveryAction<T>() {
  const client = useQueryClient()
  const request = useRef<{ input: string; key: string } | null>(null)
  return useMutation({
    mutationFn: ({ path, body }: { path: string; body: Record<string, unknown> }) => {
      const input = JSON.stringify({ path, body })
      if (request.current?.input !== input) request.current = { input, key: crypto.randomUUID() }
      return discoveryRequest<T>(path, { ...body, request_key: request.current.key })
    },
    onSuccess: () => {
      request.current = null
      void client.invalidateQueries({ queryKey: key })
      void client.invalidateQueries({ queryKey: ['market-analysis', 'runs'] })
    },
    onError: error => {
      // Refresh a concurrently edited record; form drafts keep their pinned revision.
      if ('status' in error && error.status === 409) void client.invalidateQueries({ queryKey: key })
    },
  })
}

export function useSavedStrategies() {
  return useQuery({ queryKey: [...key, 'strategies'], queryFn: ({ signal }) => discoveryRequest<{ items: SavedStrategy[] }>('/strategies', undefined, signal) })
}

export function useRecommendations(runId?: string, stockCode?: string) {
  const query = runId && stockCode ? `?${new URLSearchParams({ run_id: runId, stock_code: stockCode })}` : ''
  return useQuery({ queryKey: [...key, 'recommendations', runId, stockCode], queryFn: ({ signal }) => discoveryRequest<{ items: DiscoveryRecommendation[] }>(`/recommendations${query}`, undefined, signal) })
}

export function useDiscoveryCases() {
  return useQuery({ queryKey: [...key, 'cases'], queryFn: ({ signal }) => discoveryRequest<{ items: DiscoveryCase[] }>('/cases', undefined, signal) })
}

export function useDiscoveryCase(id: string) {
  const client = useQueryClient()
  const refreshed = useRef<string | null>(null)
  const query = useQuery({
    queryKey: [...key, 'case', id],
    queryFn: ({ signal }) => discoveryRequest<DiscoveryCase>(`/cases/${encodeURIComponent(id)}`, undefined, signal),
    enabled: !!id,
    refetchInterval: query => query.state.data?.research_runs.some(run => ['queued', 'running'].includes(run.status)) ? 2000 : false,
  })
  const completedPreparation = query.data?.research_runs
    .filter(run => run.preparation?.completed_at)
    .sort((a, b) => b.preparation!.completed_at!.localeCompare(a.preparation!.completed_at!))[0]
  const preparedKey = completedPreparation ? `${id}:${completedPreparation.id}:${completedPreparation.preparation!.completed_at}` : null
  const stockCode = query.data?.stock_code
  useEffect(() => {
    if (!preparedKey || !stockCode || refreshed.current === preparedKey) return
    refreshed.current = preparedKey
    // Collection writes are owned by the research worker. The UI only refreshes its reads.
    void client.invalidateQueries({ queryKey: ['financials', stockCode] })
  }, [client, preparedKey, stockCode])
  return query
}
