import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { MemberSession } from '@/types'

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn(), access: {
  status: 'member', session: { authenticated: true, user: { id: 'A', role: 'member' }, csrf_token: 'csrf-fixture' } as MemberSession,
} }))
vi.mock('@/api/client', () => ({ default: { get: mocks.get, post: mocks.post, delete: mocks.delete } }))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => mocks.access }))
const { useMemberPortfolio, useAddMemberPortfolioTransaction, useDeleteMemberPortfolioTransaction, useMemberPortfolioCompanies } = await import('@/hooks/useMemberPortfolio')
const clients: QueryClient[] = []
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client)
  return { client, wrap: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> }
}
afterEach(() => { cleanup(); clients.splice(0).forEach(c => c.clear()); vi.resetAllMocks(); mocks.access.status = 'member'; mocks.access.session = { authenticated: true, user: { id: 'A', role: 'member' }, csrf_token: 'csrf-fixture' } })

it('uses member-scoped query keys and never fetches personal legacy endpoints or anonymous data', async () => {
  const { client, wrap } = wrapper()
  mocks.get.mockResolvedValue({ data: { holdings: [] } })
  mocks.access.status = 'anonymous'
  const hook = renderHook(() => useMemberPortfolio(), { wrapper: wrap })
  expect(mocks.get).not.toHaveBeenCalled()
  mocks.access.status = 'member'; hook.rerender()
  await waitFor(() => expect(hook.result.current.isSuccess).toBe(true))
  expect(mocks.get).toHaveBeenCalledWith('/api/member/portfolio', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  expect(client.getQueryData(['member', 'A', 'portfolio', 'summary'])).toEqual({ holdings: [] })
  mocks.get.mockResolvedValue({ data: { holdings: ['B-only'] } })
  mocks.access.session = { ...mocks.access.session, user: { id: 'B', role: 'member' } }; hook.rerender()
  await waitFor(() => expect(hook.result.current.data?.holdings).toEqual(['B-only']))
  expect(client.getQueryData(['member', 'B', 'portfolio', 'summary'])).toEqual({ holdings: ['B-only'] })
})

it('adds and deletes with CSRF/credentials and invalidates only this member portfolio', async () => {
  const { client, wrap } = wrapper()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  mocks.post.mockResolvedValue({ data: { ok: true, id: 3 } }); mocks.delete.mockResolvedValue({ data: { ok: true } })
  const add = renderHook(useAddMemberPortfolioTransaction, { wrapper: wrap })
  const remove = renderHook(useDeleteMemberPortfolioTransaction, { wrapper: wrap })
  const body = { trade_date: '2026-01-01', kind: 'deposit' as const, amount: 100 }
  await act(() => add.result.current.mutateAsync(body))
  await act(() => remove.result.current.mutateAsync(3))
  const config = { withCredentials: true, headers: { 'X-CSRF-Token': 'csrf-fixture' } }
  expect(mocks.post).toHaveBeenCalledExactlyOnceWith('/api/member/portfolio/transactions', body, config)
  expect(mocks.delete).toHaveBeenCalledExactlyOnceWith('/api/member/portfolio/transactions/3', config)
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['member', 'A', 'portfolio'] })
  mocks.access.status = 'anonymous'; add.rerender()
  await expect(add.result.current.mutateAsync(body)).rejects.toThrow('로그인을 확인')
  expect(mocks.post).toHaveBeenCalledTimes(1)
})

it('keeps empty search disabled and uses only member company lookup', async () => {
  const { wrap } = wrapper(); mocks.get.mockResolvedValue({ data: [] })
  const hook = renderHook(({ q }) => useMemberPortfolioCompanies(q), { initialProps: { q: ' ' }, wrapper: wrap })
  expect(mocks.get).not.toHaveBeenCalled()
  hook.rerender({ q: '  가나  ' })
  await waitFor(() => expect(hook.result.current.isSuccess).toBe(true))
  expect(mocks.get).toHaveBeenCalledExactlyOnceWith('/api/member/portfolio/companies', expect.objectContaining({ params: { q: '가나' } }))
})
