import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

const get = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', () => ({ default: { get } }))
const { usePublishedDocuments } = await import('@/hooks/usePublishedDocuments')
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.splice(0).forEach(c => c.clear()); vi.clearAllMocks() })
it('uses only approved list endpoint with distinct URL query keys and revalidates on focus', async () => {
  get.mockResolvedValue({ data: { items: [], next_cursor: null } })
  const client = new QueryClient(); clients.push(client)
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const hook = renderHook(({ q, cursor }) => usePublishedDocuments(q, cursor), { wrapper, initialProps: { q: 'memory', cursor: null as string | null } })
  await waitFor(() => expect(hook.result.current.isSuccess).toBe(true))
  expect(get).toHaveBeenCalledWith('/api/public/documents', expect.objectContaining({ params: { q: 'memory', limit: 10 }, signal: expect.any(AbortSignal) }))
  const query = client.getQueryCache().find({ queryKey: ['public', 'documents', 'list', 'memory', null] })
  expect(query?.options).toMatchObject({ staleTime: 0, gcTime: 0, retry: false, refetchOnMount: 'always', refetchOnWindowFocus: 'always' })
  hook.rerender({ q: 'memory', cursor: 'opaque-next' })
  await waitFor(() => expect(get).toHaveBeenCalledWith('/api/public/documents', expect.objectContaining({ params: { q: 'memory', cursor: 'opaque-next', limit: 10 } })))
})
