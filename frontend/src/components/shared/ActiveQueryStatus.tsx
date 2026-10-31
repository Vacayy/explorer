import { useCallback, useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { isCancelled, toApiError } from '@/api/errors'

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
      fetching: query.state.fetchStatus === 'fetching',
      paused: query.state.fetchStatus === 'paused',
    }))), [cache])
  const state = useSyncExternalStore(subscribe, snapshot, () => '[]')
  const problems = JSON.parse(state) as { key: string; message: string | null; fetching: boolean; paused: boolean }[]
  if (!problems.length) return null
  const failed = problems.filter(problem => problem.message)
  const messages = [...new Set(failed.map(problem => problem.message))]
  return <div role={failed.length ? 'alert' : 'status'} className="mb-4 rounded-lg border border-destructive/20 bg-muted/30 p-3 text-sm">
    <p className="font-medium">{failed.length ? '일부 데이터를 불러오지 못했습니다.' : '네트워크 연결을 기다리고 있습니다.'}</p>
    {messages.map(message => <p key={message} className="mt-1 text-muted-foreground">{message}</p>)}
    {problems.some(problem => problem.paused) && <p className="mt-1 text-muted-foreground">연결되면 자동으로 다시 요청합니다.</p>}
    {!!failed.length && <Button variant="outline" size="sm" className="mt-2" disabled={failed.every(problem => problem.fetching || problem.paused)}
      onClick={() => { void client.refetchQueries({ type: 'active', predicate: query => query.state.status === 'error' }) }}>
      {failed.every(problem => problem.fetching) ? '다시 시도 중…' : '실패한 데이터 다시 불러오기'}
    </Button>}
  </div>
}
