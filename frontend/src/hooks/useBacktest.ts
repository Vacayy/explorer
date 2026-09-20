import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '@/api/client'
import type { BacktestConfig, BacktestRun, BacktestSpec, BacktestStatus } from '@/components/analysis/backtestTypes'

const ROOT = `${API_BASE}/api/analysis/backtests`
const listKey = ['market-backtest', 'runs'] as const
const runKey = (id: string | null) => ['market-backtest', 'run', id] as const

export function isBacktestActive(status?: BacktestStatus) {
  return status === 'queued' || status === 'preparing' || status === 'running'
}

function newestRun(current: BacktestRun | undefined, incoming: BacktestRun) {
  if (!current) return incoming
  if (!isBacktestActive(current.status) && isBacktestActive(incoming.status)) return current
  return Date.parse(current.updated_at) > Date.parse(incoming.updated_at) ? current : incoming
}

async function request<T>(path = '', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    const detail = data?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(' · ')
      : null
    throw new Error(message || `요청을 처리하지 못했습니다 (${response.status}).`)
  }
  return response.json() as Promise<T>
}

export function backtestArtifactUrl(runId: string, name: string) {
  return `${ROOT}/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}`
}

export function useBacktest(runId: string | null, onCreated: (id: string) => void) {
  const client = useQueryClient()
  const config = useQuery({
    queryKey: ['market-backtest', 'config'],
    queryFn: ({ signal }) => request<BacktestConfig>('/config', undefined, signal),
    staleTime: 60_000,
  })
  const runs = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) => request<{ items: BacktestRun[] }>('', undefined, signal),
    refetchInterval: 10_000,
  })
  const detail = useQuery({
    queryKey: runKey(runId),
    queryFn: async ({ signal }) => {
      const incoming = await request<BacktestRun>(`/${encodeURIComponent(runId!)}`, undefined, signal)
      return newestRun(client.getQueryData<BacktestRun>(runKey(runId)), incoming)
    },
    enabled: !!runId,
    refetchInterval: query => query.state.error ? false : !query.state.data || isBacktestActive(query.state.data.status) ? 2000 : false,
  })
  const update = (run: BacktestRun) => {
    client.setQueryData<BacktestRun>(runKey(run.id), current => newestRun(current, run))
    client.invalidateQueries({ queryKey: listKey })
  }
  const start = useMutation({
    mutationFn: (spec: BacktestSpec) => request<BacktestRun>('', { spec }),
    retry: false,
    onSuccess: run => { update(run); onCreated(run.id) },
    onError: () => { client.invalidateQueries({ queryKey: listKey }) },
  })
  const cancel = useMutation({
    mutationFn: () => request<BacktestRun>(`/${encodeURIComponent(runId!)}/cancel`, {}),
    onSuccess: update,
  })
  return { config, runs, detail, start, cancel }
}
