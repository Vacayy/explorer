import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApiError } from '@/api/errors'
import { usePublishedDocument } from '@/hooks/usePublishedDocument'

const get = vi.hoisted(() => vi.fn())
vi.mock('@/api/client.ts', () => ({ default: { get } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

it('only fetches the approved public endpoint and removes cached documents on unmount', async () => {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  get.mockResolvedValue({ data: { id: 12, content: 'approved' } })
  const hook = renderHook(({ id }) => usePublishedDocument(id), { initialProps: { id: null as number | null }, wrapper })
  expect(get).not.toHaveBeenCalled()
  hook.rerender({ id: 12 })
  await waitFor(() => expect(hook.result.current.isSuccess).toBe(true))
  expect(get).toHaveBeenCalledExactlyOnceWith('/api/public/documents/12', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  get.mockRejectedValue(new ApiError('not approved', 404))
  await hook.result.current.refetch()
  await waitFor(() => expect(hook.result.current.isError).toBe(true))
  expect(get).toHaveBeenCalledTimes(2)
  hook.unmount()
  await waitFor(() => expect(client.getQueryData(['public', 'documents', 12])).toBeUndefined())
  client.clear()
})
