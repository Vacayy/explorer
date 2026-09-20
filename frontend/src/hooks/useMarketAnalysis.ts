import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { EventType } from '@ag-ui/core'
import { API_BASE } from '@/api/client'
import { eventLog, eventRun, isTerminal, newestRun, parseAnalysisEvent, streamCanRest } from '@/components/analysis/events'
import type { AnalysisChart, AnalysisRun, AnalysisSpec } from '@/components/analysis/types'

const ROOT = `${API_BASE}/api/analysis/runs`
const runKey = (id: string | null) => ['market-analysis', 'run', id] as const
const listKey = ['market-analysis', 'runs'] as const
const threadKey = (id: string | null) => ['market-analysis', 'thread', id] as const

export type ThreadTurn = AnalysisRun & { parent_run_id: string | null }
export interface AnalysisThread { root_id: string; items: ThreadTurn[] }

async function request<T>(path = '', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(typeof data?.detail === 'string' ? data.detail : `요청을 처리하지 못했습니다 (${response.status}).`)
  }
  return response.json() as Promise<T>
}

export function analysisArtifactUrl(runId: string, artifactId: string) {
  return `${ROOT}/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`
}

export function useAnalysisChart(runId: string, code: string | null) {
  return useQuery({
    queryKey: ['market-analysis', 'chart', runId, code],
    queryFn: ({ signal }) => request<AnalysisChart>(`/${encodeURIComponent(runId)}/chart/${encodeURIComponent(code!)}`, undefined, signal),
    enabled: !!code,
    staleTime: Infinity,
  })
}

/** The focused run with its ancestors and every follow-up of the same root (D-184). */
export function useAnalysisThread(runId: string | null) {
  return useQuery({
    queryKey: threadKey(runId),
    queryFn: ({ signal }) => request<AnalysisThread>(`/${encodeURIComponent(runId!)}/thread`, undefined, signal),
    enabled: !!runId,
    refetchInterval: query => query.state.data?.items.some(item => !isTerminal(item.status)) ? 2500 : false,
  })
}

export function useMarketAnalysis(runId: string | null, onCreated: (id: string) => void) {
  const client = useQueryClient()
  const runs = useQuery({ queryKey: listKey, queryFn: ({ signal }) => request<{ items: AnalysisRun[] }>('', undefined, signal), refetchInterval: 15_000 })
  const detail = useQuery({
    queryKey: runKey(runId),
    queryFn: async ({ signal }) => {
      const incoming = await request<AnalysisRun>(`/${encodeURIComponent(runId!)}`, undefined, signal)
      return newestRun(client.getQueryData<AnalysisRun>(runKey(runId)), incoming)
    },
    enabled: !!runId,
    refetchInterval: query => !query.state.data || !isTerminal(query.state.data.status) ? 2500 : false,
  })
  const [stream, setStream] = useState<{ id: string; disconnected: boolean; logs: { sequence: number; text: string }[] }>({ id: '', disconnected: false, logs: [] })

  useEffect(() => {
    if (!runId) return
    let after = 0
    let source: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let disposed = false
    const connect = () => {
      if (disposed) return
      source = new EventSource(`${ROOT}/${encodeURIComponent(runId)}/events?after=${after}`)
      source.onopen = () => setStream(previous => ({ id: runId, disconnected: false, logs: previous.id === runId ? previous.logs : [] }))
      source.onmessage = message => {
        const event = parseAnalysisEvent(message.data)
        if (!event || event.sequence <= after) return
        after = event.sequence
        const incoming = eventRun(event, runId)
        if (incoming) {
          client.setQueryData<AnalysisRun>(runKey(runId), current => newestRun(current, incoming))
          if (isTerminal(incoming.status)) { client.invalidateQueries({ queryKey: listKey }); client.invalidateQueries({ queryKey: threadKey(runId) }) }
        }
        const log = eventLog(event)
        if (log) setStream(previous => ({ id: runId, disconnected: false, logs: [...(previous.id === runId ? previous.logs.filter(item => item.sequence !== event.sequence) : []), { sequence: event.sequence, text: log }].sort((a, b) => a.sequence - b.sequence).slice(-100) }))
        if (event.type === EventType.RUN_FINISHED || event.type === EventType.RUN_ERROR) {
          // A replay can include several old interrupt finishes. Read through
          // the server's EOF so later steps and the final state are not lost.
          client.invalidateQueries({ queryKey: runKey(runId) })
        }
      }
      source.onerror = () => {
        source?.close()
        if (disposed) return
        if (streamCanRest(client.getQueryData<AnalysisRun>(runKey(runId))?.status)) return
        setStream(previous => ({ id: runId, disconnected: true, logs: previous.id === runId ? previous.logs : [] }))
        retry = setTimeout(connect, 3000)
      }
    }
    connect()
    // Disconnecting a view only detaches transport. Cancellation is a POST below.
    return () => { disposed = true; source?.close(); if (retry) clearTimeout(retry) }
  }, [runId, detail.data?.pending?.id, client])

  const update = (run: AnalysisRun) => {
    client.setQueryData<AnalysisRun>(runKey(run.id), current => newestRun(current, run))
    client.invalidateQueries({ queryKey: listKey })
  }
  const start = useMutation({
    mutationFn: (body: { question: string; request_key: string; as_of?: string; spec?: Partial<AnalysisSpec>; parent_run_id?: string; scope?: 'universe' | 'candidates'; date_policy?: 'same' | 'latest'; default_within_days?: number }) => request<AnalysisRun>('', body),
    onSuccess: (run, body) => {
      update(run)
      if (body.parent_run_id) {
        // Seed the new run's thread so the previous turns stay on screen while the server catches up.
        const previous = client.getQueryData<AnalysisThread>(threadKey(runId))
        client.setQueryData<AnalysisThread>(threadKey(run.id), { root_id: previous?.root_id ?? body.parent_run_id, items: [...(previous?.items ?? []).filter(item => item.id !== run.id), { ...run, parent_run_id: body.parent_run_id }] })
      }
      onCreated(run.id)
    },
  })
  const resume = useMutation({
    mutationFn: (body: { interrupt_id: string; payload: Record<string, unknown> }) => request<AnalysisRun>(`/${encodeURIComponent(runId!)}/resume`, body),
    onSuccess: update,
  })
  const cancel = useMutation({
    mutationFn: () => request<AnalysisRun>(`/${encodeURIComponent(runId!)}/cancel`, {}),
    onSuccess: update,
  })
  return { runs, detail, start, resume, cancel, logs: stream.id === runId ? stream.logs : [], disconnected: stream.id === runId && stream.disconnected }
}
