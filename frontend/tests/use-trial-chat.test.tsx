import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { TrialChatReply } from '@/types/trialChat'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/client', () => ({ default: api }))
const { useTrialChat } = await import('@/hooks/useTrialChat')
const session = { remaining: 10, limit: 10, csrf_token: 'csrf-token' }
const reply: TrialChatReply = { answer: '<b>plain text</b>', citations: [{ id: 'D1', title: '공개 자료', url: '/doc/1' }], partial: false, remaining: 9 }

beforeEach(() => {
  api.get.mockResolvedValue({ data: session })
  api.post.mockResolvedValue({ data: reply })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks() })

it('sends credentials and CSRF with body-only history, then keeps the reply in component memory', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem')
  const { result } = renderHook(() => useTrialChat())
  await waitFor(() => expect(result.current.status).toBe('empty'))
  await act(async () => { await result.current.send('질문 canary', { document_ids: [1] }) })
  expect(api.post).toHaveBeenCalledExactlyOnceWith('/api/public/chat', {
    question: '질문 canary', history: [], document_ids: [1],
  }, expect.objectContaining({ withCredentials: true, timeout: 200_000, headers: { 'X-CSRF-Token': 'csrf-token' }, signal: expect.any(AbortSignal) }))
  expect(result.current.messages[1]).toEqual({ role: 'assistant', content: '<b>plain text</b>', citations: reply.citations, partial: false })
  expect(result.current.session?.remaining).toBe(9)
  expect(storage).not.toHaveBeenCalled()
})

it('passes only the last four plain role/content messages, without citation metadata', async () => {
  const { result } = renderHook(() => useTrialChat())
  await waitFor(() => expect(result.current.loading).toBe(false))
  for (const question of ['one', 'two', 'three', 'four']) {
    await act(async () => { await result.current.send(question) })
  }
  expect(api.post.mock.calls[3][1].history).toEqual([
    { role: 'user', content: 'two' }, { role: 'assistant', content: reply.answer },
    { role: 'user', content: 'three' }, { role: 'assistant', content: reply.answer },
  ])
})

it('does not retry rejected POST and refreshes remaining after quota denial without retaining raw errors', async () => {
  api.post.mockRejectedValue({ response: { status: 429, data: { detail: 'private error canary' } }, config: { data: 'question canary' } })
  const { result } = renderHook(() => useTrialChat())
  await waitFor(() => expect(result.current.loading).toBe(false))
  api.get.mockResolvedValue({ data: { ...session, remaining: 0 } })
  await act(async () => { await result.current.send('question canary') })
  expect(api.post).toHaveBeenCalledTimes(1)
  expect(api.get).toHaveBeenCalledTimes(2)
  expect(result.current.session?.remaining).toBe(0)
  expect(result.current.messages).toEqual([])
  expect(result.current.error).not.toContain('canary')
  await act(async () => { await result.current.send('second') })
  expect(api.post).toHaveBeenCalledTimes(1)
})

it('blocks duplicate submits before React rerenders', async () => {
  let resolve!: (value: { data: TrialChatReply }) => void
  api.post.mockReturnValue(new Promise(r => { resolve = r }))
  const { result } = renderHook(() => useTrialChat())
  await waitFor(() => expect(result.current.loading).toBe(false))
  let first!: Promise<boolean>
  act(() => { first = result.current.send('first'); void result.current.send('duplicate') })
  expect(api.post).toHaveBeenCalledTimes(1)
  await act(async () => { resolve({ data: reply }); await first })
})

it('aborts and ignores late replies after reset', async () => {
  let resolve!: (value: { data: TrialChatReply }) => void
  api.post.mockReturnValue(new Promise(r => { resolve = r }))
  const { result } = renderHook(() => useTrialChat())
  await waitFor(() => expect(result.current.loading).toBe(false))
  let request!: Promise<boolean>
  act(() => { request = result.current.send('old question') })
  const signal = api.post.mock.calls[0][2].signal
  await act(async () => { await result.current.reset() })
  expect(signal.aborted).toBe(true)
  await act(async () => { resolve({ data: reply }); await request })
  expect(result.current.messages).toEqual([])
  expect(result.current.session?.remaining).toBe(10)
})

it('clears conversation on identity change and aborts outstanding requests on unmount', async () => {
  const { result, rerender, unmount } = renderHook(({ identity }) => useTrialChat(identity), { initialProps: { identity: 'A' } })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => { await result.current.send('A question') })
  rerender({ identity: 'B' })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.messages).toEqual([])
  let resolve!: (value: { data: TrialChatReply }) => void
  api.post.mockReturnValue(new Promise(r => { resolve = r }))
  let request!: Promise<boolean>
  act(() => { request = result.current.send('B question') })
  const signal = api.post.mock.calls.at(-1)![2].signal
  unmount()
  expect(signal.aborted).toBe(true)
  await act(async () => { resolve({ data: reply }); await request })
})

it('fails closed when session refresh after an error fails', async () => {
  const { result } = renderHook(() => useTrialChat())
  await waitFor(() => expect(result.current.loading).toBe(false))
  api.post.mockRejectedValue(new Error('transport failed'))
  api.get.mockRejectedValue(new Error('session failed'))
  await act(async () => { await result.current.send('question') })
  expect(result.current.session).toBeNull()
  expect(result.current.status).toBe('error')
  await act(async () => { await result.current.send('question again') })
  expect(api.post).toHaveBeenCalledTimes(1)
})
