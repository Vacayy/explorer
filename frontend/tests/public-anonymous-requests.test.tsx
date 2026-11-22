// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemberAccessProvider } from '@/components/auth/MemberAccess'
import { useSaved } from '@/hooks/useSaved'
import { useProjects } from '@/components/study/useProjects'
import { useApprovalsCount } from '@/components/layout/Inboxes'

const auth = vi.hoisted(() => ({ session: vi.fn() }))
const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/auth', () => ({ getMemberSession: auth.session, logoutMember: vi.fn(), googleLoginUrl: () => '/login' }))
vi.mock('@/lib/memberReset', () => ({ clearMemberBrowserState: vi.fn(), leaveMemberSession: vi.fn() }))
vi.mock('@/api/client', () => ({ default: http, API_BASE: '' }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

function Probe() { useSaved(); useProjects(); useApprovalsCount(); return null }

async function urlsFor(session: unknown) {
  auth.session.mockResolvedValue(session)
  http.get.mockResolvedValue({ data: [] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemberAccessProvider enabled><Probe /></MemberAccessProvider></QueryClientProvider>)
  await vi.waitFor(() => expect(auth.session).toHaveBeenCalled())
  await new Promise((r) => setTimeout(r, 50))
  return http.get.mock.calls.map((call) => String(call[0]))
}

it('asks no member or operator API for an anonymous public reader', async () => {
  const urls = await urlsFor({ authenticated: false, user: null, csrf_token: null, login_available: true })
  expect(urls.filter((u) => /saved|study-projects|approvals/.test(u))).toEqual([])
})

it('asks the member APIs, not the operator ones, for a signed-in member', async () => {
  const urls = await urlsFor({ authenticated: true, user: { id: 'm', role: 'member' }, csrf_token: 't', login_available: true })
  expect(urls.some((u) => u.includes('/api/spine/saved'))).toBe(true)
  expect(urls.some((u) => u.includes('/api/spine/study-projects'))).toBe(true)
  expect(urls.some((u) => u.includes('/api/spine/approvals'))).toBe(false)
})
