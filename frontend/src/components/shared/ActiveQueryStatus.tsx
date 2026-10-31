import { useCallback, useSyncExternalStore } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiQuery } from '@/api/query'
import type { RuntimeStatus } from '@/types'
import { Button } from '@/components/ui/button'
import { isCancelled, toApiError, type ApiError } from '@/api/errors'
import { issueField } from '@/api/telemetry'

/** '자세히'에 보일 원인 — API와 첫 검증 실패 필드 */
const causeOf = (error: ApiError) => error.endpoint
  ? `${error.endpoint}${error.status ? ` ${error.status}` : ''}${issueField(error) ? ` · ${issueField(error)}: ${error.issues?.[0]?.message ?? ''}` : ''}`
  : null

/** Persistent fallback for legacy/independent panels that do not yet render QueryState.
 * Only mounted observers count: prefetch errors and old routes must not pollute this page.
 */
export function ActiveQueryStatus() {
  const client = useQueryClient()
  const cache = client.getQueryCache()
  const subscribe = useCallback((notify: () => void) => cache.subscribe(notify), [cache])
  const snapshot = useCallback(() => JSON.stringify(cache.getAll()
    .filter(query => query.isActive() && !isCancelled(query.state.error) && (query.state.status === 'error' || query.state.fetchStatus === 'paused'))
    .map(query => ({
      key: query.queryHash,
      message: query.state.error ? toApiError(query.state.error).message : null,
      cause: query.state.error ? causeOf(toApiError(query.state.error)) : null,
      schema: query.state.error ? toApiError(query.state.error).kind === 'schema' : false,
      fetching: query.state.fetchStatus === 'fetching',
      paused: query.state.fetchStatus === 'paused',
    }))), [cache])
  const state = useSyncExternalStore(subscribe, snapshot, () => '[]')
  const problems = JSON.parse(state) as { key: string; message: string | null; cause: string | null; schema: boolean; fetching: boolean; paused: boolean }[]
  // 계약 오류가 있으면 백엔드가 옛 코드로 돌고 있는지 확인 — 코드 수정 후 재시작 전이 가장 흔한 원인(2026-10-31)
  const runtime = useQuery({ ...apiQuery<RuntimeStatus>({ key: ['admin', 'runtime'], url: '/api/spine/admin/runtime', staleTime: 30_000 }),
    enabled: problems.some(problem => problem.schema) })
  if (!problems.length) return null
  const failed = problems.filter(problem => problem.message)
  const messages = [...new Set(failed.map(problem => problem.message))]
  return <div role={failed.length ? 'alert' : 'status'} className="mb-4 rounded-lg border border-destructive/20 bg-muted/30 p-3 text-sm">
    <p className="font-medium">{failed.length ? '일부 데이터를 불러오지 못했습니다.' : '네트워크 연결을 기다리고 있습니다.'}</p>
    {messages.map(message => <p key={message} className="mt-1 text-muted-foreground">{message}</p>)}
    {runtime.data?.stale && <p className="mt-1 text-muted-foreground">백엔드가 {runtime.data.stale_minutes}분 전 바뀐 코드({runtime.data.changed_file})로 아직 재시작되지 않았습니다. 서버를 재시작하면 해결될 수 있습니다.</p>}
    {failed.some(problem => problem.cause) && <details className="mt-1 text-caption text-muted-foreground">
      <summary className="cursor-pointer">자세히 · 운영 점검에도 기록됩니다</summary>
      <ul className="mt-1 list-disc pl-5">{[...new Set(failed.flatMap(problem => problem.cause ? [problem.cause] : []))].map(cause => <li key={cause} className="break-all font-mono">{cause}</li>)}</ul>
    </details>}
    {problems.some(problem => problem.paused) && <p className="mt-1 text-muted-foreground">연결되면 자동으로 다시 요청합니다.</p>}
    {!!failed.length && <Button variant="outline" size="sm" className="mt-2" disabled={failed.every(problem => problem.fetching || problem.paused)}
      onClick={() => { void client.refetchQueries({ type: 'active', predicate: query => query.state.status === 'error' }) }}>
      {failed.every(problem => problem.fetching) ? '다시 시도 중…' : '실패한 데이터 다시 불러오기'}
    </Button>}
  </div>
}
