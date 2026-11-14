import type { ReactNode } from 'react'
import { ErrorState, EmptyState } from './ErrorState'
import { TableSkeleton } from './Skeleton'
import { toApiError } from '@/api/errors'

/** Undefined means no successful response yet; null/[] are successful empty responses. */
export function QueryState<T>({ query, children, isEmpty = value => value === null || (Array.isArray(value) && value.length === 0), emptyMessage, loading, className }: {
  query: { data: T | undefined; error: unknown; isPending: boolean; isFetching: boolean; fetchStatus: 'fetching' | 'paused' | 'idle'; refetch: () => unknown }
  children: (data: T) => ReactNode
  isEmpty?: (data: T) => boolean
  emptyMessage?: string
  loading?: ReactNode
  /** 데이터 칸 감싸개 — 고정 높이 칸 안에서 남은 높이를 채울 때(flex) */
  className?: string
}) {
  const { data, error, isFetching, fetchStatus } = query
  if (data === undefined) {
    if (error) return <ErrorState error={error} onRetry={() => { void query.refetch() }} retrying={isFetching} />
    if (fetchStatus === 'paused') return <EmptyState message="네트워크 연결을 기다리고 있습니다. 연결되면 자동으로 다시 요청합니다." />
    if (fetchStatus === 'idle') return <EmptyState message="조회 조건을 선택해 주세요." />
    return <div role="status" aria-label="데이터 불러오는 중" aria-busy="true">{loading ?? <TableSkeleton />}</div>
  }
  return <div aria-busy={isFetching} className={className}>
    {!!error && <ErrorState message={`최신 데이터를 불러오지 못해 이전 결과를 표시합니다. ${toApiError(error).message}`} onRetry={() => { void query.refetch() }} retrying={isFetching} />}
    {fetchStatus === 'paused' && <p role="status" className="text-sm text-muted-foreground">연결을 기다리는 동안 이전 결과를 표시합니다.</p>}
    {isFetching && <p role="status" className="text-sm text-muted-foreground">업데이트 중…</p>}
    {isEmpty(data) ? <EmptyState message={emptyMessage} /> : children(data)}
  </div>
}
