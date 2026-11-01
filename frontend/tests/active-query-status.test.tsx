import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { ActiveQueryStatus } from '../src/components/shared/ActiveQueryStatus'
import { ApiError } from '../src/api/errors'

const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0 })
function client() { const value = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); clients.push(value); return value }

it('keeps failures visible for legacy panels, retries only failed requests and clears after recovery', async () => {
  const qc = client()
  const failed = vi.fn().mockRejectedValueOnce(new ApiError('네트워크 연결 실패', undefined, { kind: 'network' })).mockResolvedValue([])
  const good = vi.fn().mockResolvedValue(['healthy'])
  function Panel() {
    useQuery({ queryKey: ['failed'], queryFn: failed })
    useQuery({ queryKey: ['healthy'], queryFn: good, staleTime: Infinity })
    return <p>메뉴 유지</p>
  }
  render(<QueryClientProvider client={qc}><ActiveQueryStatus /><Panel /></QueryClientProvider>)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByText('메뉴 유지')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '실패한 데이터 다시 불러오기' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(failed).toHaveBeenCalledTimes(2)
  expect(good).toHaveBeenCalledTimes(1)
})

it('does not show failures from unmounted or disabled queries', async () => {
  const qc = client()
  await qc.fetchQuery({ queryKey: ['old-page'], queryFn: () => Promise.reject(new ApiError('이전 화면 실패')) }).catch(() => {})
  function Disabled() { useQuery({ queryKey: ['old-page'], queryFn: () => [], enabled: false }); return null }
  render(<QueryClientProvider client={qc}><ActiveQueryStatus /><Disabled /></QueryClientProvider>)
  expect(screen.queryByRole('alert')).toBeNull()
})
