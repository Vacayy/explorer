// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MemberAccessProvider } from '@/components/auth/MemberAccess'
import { DocRelated } from '@/components/doc/DocRelated'

const auth = vi.hoisted(() => ({ session: vi.fn() }))
const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/auth', () => ({ getMemberSession: auth.session, logoutMember: vi.fn(), googleLoginUrl: () => '/login' }))
vi.mock('@/lib/memberReset', () => ({ clearMemberBrowserState: vi.fn(), leaveMemberSession: vi.fn() }))
vi.mock('@/api/client', () => ({ default: http }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const anonymous = { authenticated: false, user: null, csrf_token: null, login_available: true }
const member = { authenticated: true, user: { id: 'm', role: 'member' }, csrf_token: 't', login_available: true }

function mount(claims: unknown) {
  http.get.mockImplementation(async (url: string) => ({ data: url.endsWith('/claims') ? claims : [] }))
  http.post.mockResolvedValue({ data: { status: 'running' } })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><MemberAccessProvider enabled>
    <DocRelated docId={7} />
  </MemberAccessProvider></MemoryRouter></QueryClientProvider>)
}

it('shows saved claims to an anonymous reader without queuing a job', async () => {
  auth.session.mockResolvedValue(anonymous)
  mount({ status: 'ok', claims: [{ claim: '기존 논점', related: [{ id: 9, title: '관련 자료', quote: null, source_type: 'blog', published_at: '2026-11-20' }] }] })
  expect(await screen.findByText('‘기존 논점’ 논점')).toBeTruthy()
  expect(http.post).not.toHaveBeenCalled()
})

it('never queues a job when an anonymous reader opens a document without claims', async () => {
  auth.session.mockResolvedValue(anonymous)
  mount({ status: 'none', claims: [] })
  await vi.waitFor(() => expect(http.get).toHaveBeenCalled())
  await new Promise((r) => setTimeout(r, 50))
  expect(http.post).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '논점 정리하기' })).toBeNull()
})

it('lets a signed-in member ask for claims, only on request', async () => {
  auth.session.mockResolvedValue(member)
  mount({ status: 'none', claims: [] })
  const button = await screen.findByRole('button', { name: '논점 정리하기' })
  expect(http.post).not.toHaveBeenCalled()
  fireEvent.click(button)
  await vi.waitFor(() => expect(http.post).toHaveBeenCalledWith('/api/spine/doc/7/claims'))
})
