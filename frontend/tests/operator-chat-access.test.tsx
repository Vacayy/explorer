import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

const state = vi.hoisted(() => ({
  status: 'anonymous',
  session: { authenticated: false, user: null as null | { id: string; role: string }, csrf_token: null as null | string },
  post: vi.fn(), patch: vi.fn(),
}))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => ({ status: state.status }) }))
vi.mock('@/components/chat/ChatPage', () => ({ default: () => <div>operator chat fixture</div> }))
vi.mock('@/components/chat/PublicTrialChatPage', () => ({ PublicTrialChatPage: () => <div>trial chat fixture</div> }))
vi.mock('@/lib/accessMode', () => ({ PUBLIC_ACCESS: true }))
vi.mock('@/api/auth', () => ({ getMemberSession: async () => state.session }))
vi.mock('@/api/client', () => ({ default: { post: state.post, patch: state.patch }, API_BASE: '' }))

const { PublicChatRoute } = await import('@/components/auth/PublicContent')
const { askQuestion, renameConversation } = await import('@/api/spine')

beforeEach(() => {
  state.status = 'anonymous'
  state.session = { authenticated: false, user: null, csrf_token: null }
  state.post.mockReset().mockResolvedValue({ data: {} })
  state.patch.mockReset().mockResolvedValue({ data: {} })
})
afterEach(cleanup)

it('shows existing chat only to an operator', () => {
  const view = render(<PublicChatRoute />)
  expect(screen.getByText('trial chat fixture')).toBeTruthy()
  state.status = 'operator'
  view.rerender(<PublicChatRoute />)
  expect(screen.getByText('operator chat fixture')).toBeTruthy()
})

it('sends the operator session CSRF token and blocks anonymous writes', async () => {
  await expect(askQuestion({ question: 'test' })).rejects.toThrow()
  expect(state.post).not.toHaveBeenCalled()
  state.session = { authenticated: true, user: { id: 'test', role: 'operator' }, csrf_token: 'csrf-fixture' }
  await askQuestion({ question: 'test' })
  expect(state.post).toHaveBeenCalledWith('/api/spine/ask', { question: 'test' },
    expect.objectContaining({ withCredentials: true, headers: { 'X-CSRF-Token': 'csrf-fixture' } }))
  await renameConversation({ id: 1, title: 'test' })
  expect(state.patch).toHaveBeenCalledWith('/api/spine/conversations/1', { title: 'test' },
    expect.objectContaining({ withCredentials: true, headers: { 'X-CSRF-Token': 'csrf-fixture' } }))
})
