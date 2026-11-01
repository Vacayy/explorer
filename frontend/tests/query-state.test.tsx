import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryState } from '../src/components/shared/QueryState'
import { ErrorBoundary } from '../src/components/shared/ErrorBoundary'
import { ApiError } from '../src/api/errors'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
const base = { data: undefined as string[] | undefined, error: null as unknown, isPending: true, isFetching: true, fetchStatus: 'fetching' as const, refetch: vi.fn() }
const child = (data: string[]) => <p>{data.join(',')}</p>
it('renders loading, paused and disabled states without rendering data', () => {
  const { rerender } = render(<QueryState query={base}>{child}</QueryState>)
  expect(screen.getByRole('status').getAttribute('aria-busy')).toBe('true')
  rerender(<QueryState query={{ ...base, isFetching: false, fetchStatus: 'paused' }}>{child}</QueryState>)
  expect(screen.getByText(/네트워크 연결을 기다리고/)).toBeTruthy()
  rerender(<QueryState query={{ ...base, isFetching: false, fetchStatus: 'idle' }}>{child}</QueryState>)
  expect(screen.getByText(/조회 조건/)).toBeTruthy()
})
it('shows error before empty and supports retry', () => {
  const query = { ...base, isFetching: false, error: new ApiError('연결 실패') }
  render(<QueryState query={query}>{child}</QueryState>)
  expect(screen.getByRole('alert').textContent).toContain('연결 실패')
  expect(screen.queryByText('데이터가 없습니다.')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
  expect(query.refetch).toHaveBeenCalled()
})
it('renders successful empty results and keeps data during background failures', () => {
  const { rerender } = render(<QueryState query={{ ...base, data: [], isFetching: false, isPending: false }}>{child}</QueryState>)
  expect(screen.getByText('데이터가 없습니다.')).toBeTruthy()
  rerender(<QueryState query={{ ...base, data: ['기존 값'], isPending: false, isFetching: false, error: new Error('bad') }}>{child}</QueryState>)
  expect(screen.getByText('기존 값')).toBeTruthy()
  expect(screen.getByRole('alert').textContent).toContain('이전 결과')
})
it('isolates a failed subtree and recovers through reset', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  let fail = true
  function Child() { if (fail) throw new Error('bad render'); return <p>복구됨</p> }
  render(<><p>메뉴 유지</p><ErrorBoundary onReset={() => { fail = false }}><Child /></ErrorBoundary></>)
  expect(screen.getByText('메뉴 유지')).toBeTruthy()
  expect(screen.getByRole('alert')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
  expect(screen.getByText('복구됨')).toBeTruthy()
})
