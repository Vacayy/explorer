import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { MemberSession } from '../src/types'

vi.mock('@/api/auth', () => ({ getMemberSession: vi.fn(), logoutMember: vi.fn(),
  googleLoginUrl: (path: string) => '/api/auth/google/start?return_to=' + encodeURIComponent(path) }))
vi.mock('@/lib/memberReset', async importOriginal => ({ ...await importOriginal<typeof import('../src/lib/memberReset')>(), leaveMemberSession: vi.fn() }))
const { getMemberSession, logoutMember } = await import('../src/api/auth')
const { leaveMemberSession } = await import('../src/lib/memberReset')
const { MemberAccessProvider, AccountControl, MEMBER_SESSION_KEY } = await import('../src/components/auth/MemberAccess')
const anonymous: MemberSession = { login_available: true, chat_available: true, authenticated: false, user: null, csrf_token: null }
const member: MemberSession = { login_available: true, chat_available: true, authenticated: true, user: { id: 'member-a', role: 'member' }, csrf_token: 'fixture-token' }
const clients: QueryClient[] = []

afterEach(() => { cleanup(); clients.splice(0).forEach(c => c.clear()); vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear() })
function show(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/home/kr?range=1m']}>
    <MemberAccessProvider enabled={enabled}><p>공용 시장 화면</p><AccountControl /></MemberAccessProvider>
  </MemoryRouter></QueryClientProvider>)
  return client
}

it('keeps the market visible while loading and gives anonymous users a safe return link', async () => {
  let resolve!: (value: MemberSession) => void
  vi.mocked(getMemberSession).mockReturnValue(new Promise(done => { resolve = done }))
  show()
  expect(screen.getByText('공용 시장 화면')).toBeTruthy()
  expect(screen.getByRole('status').textContent).toBe('계정 확인 중')
  resolve(anonymous)
  const link = await screen.findByRole('link', { name: 'Google 로그인' })
  expect(link.getAttribute('href')).toContain(encodeURIComponent('/home/kr?range=1m'))
  expect(localStorage.length).toBe(0)
  expect(sessionStorage.length).toBe(0)
})

it('retries a failed session check without blocking public data', async () => {
  vi.mocked(getMemberSession).mockRejectedValueOnce(new Error('fixture')).mockResolvedValue(anonymous)
  show()
  fireEvent.click(await screen.findByRole('button', { name: '로그인 확인 재시도' }))
  expect(await screen.findByRole('link', { name: 'Google 로그인' })).toBeTruthy()
  expect(screen.getByText('공용 시장 화면')).toBeTruthy()
})

it('only clears personal state after confirmed logout, preserving theme', async () => {
  vi.mocked(getMemberSession).mockResolvedValue(member)
  vi.mocked(logoutMember).mockResolvedValue({ ok: true })
  const client = show()
  client.setQueryData(['portfolio', 'private'], { note: 'private-canary' })
  localStorage.setItem('project-note-draft-1', 'private-canary')
  localStorage.setItem('explorer.shell.thread', '123')
  localStorage.setItem('theme', 'dark')
  sessionStorage.setItem('pending-answer-convs', '[123]')
  fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))
  await waitFor(() => expect(leaveMemberSession).toHaveBeenCalledOnce())
  expect(logoutMember).toHaveBeenCalledWith('fixture-token')
  expect(client.getQueryData(['portfolio', 'private'])).toBeUndefined()
  expect(localStorage.getItem('project-note-draft-1')).toBeNull()
  expect(localStorage.getItem('explorer.shell.thread')).toBeNull()
  expect(sessionStorage.getItem('pending-answer-convs')).toBeNull()
  expect(localStorage.getItem('theme')).toBe('dark')
})

it('does not pretend logout succeeded when the request fails', async () => {
  vi.mocked(getMemberSession).mockResolvedValue(member)
  vi.mocked(logoutMember).mockRejectedValue(new Error('fixture'))
  show(); localStorage.setItem('project-note-draft-1', 'unsaved')
  fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(leaveMemberSession).not.toHaveBeenCalled()
  expect(localStorage.getItem('project-note-draft-1')).toBe('unsaved')
})

it('clears old cached and persisted state when a confirmed account changes', async () => {
  vi.mocked(getMemberSession).mockResolvedValue(member)
  const client = show()
  await screen.findByText('로그인됨')
  client.setQueryData(['private'], { note: 'old-account' })
  sessionStorage.setItem('explorer:discovery:stack:v1', 'old-account')
  client.setQueryData(MEMBER_SESSION_KEY, { ...member, user: { id: 'member-b', role: 'member' } })
  await waitFor(() => expect(leaveMemberSession).toHaveBeenCalledOnce())
  expect(client.getQueryData(['private'])).toBeUndefined()
  expect(sessionStorage.getItem('explorer:discovery:stack:v1')).toBeNull()
})

it('does not call authentication in the existing private build', () => {
  show(false)
  expect(getMemberSession).not.toHaveBeenCalled()
  expect(screen.queryByRole('link')).toBeNull()
})

it('also clears prior state when the same account loses its operator role', async () => {
  vi.mocked(getMemberSession).mockResolvedValue({ ...member, user: { id: 'member-a', role: 'operator' } })
  const client = show()
  await screen.findByText('운영자')
  client.setQueryData(['operator', 'private'], { note: 'old-role' })
  client.setQueryData(MEMBER_SESSION_KEY, member)
  await waitFor(() => expect(leaveMemberSession).toHaveBeenCalledOnce())
  expect(client.getQueryData(['operator', 'private'])).toBeUndefined()
})

it('shows confirmed unavailable login without creating an OAuth link', async () => {
  vi.mocked(getMemberSession).mockResolvedValue({ ...anonymous, login_available: false, chat_available: false })
  show()
  expect(await screen.findByText('로그인 준비 중')).toBeTruthy()
  expect(screen.queryByRole('link', { name: 'Google 로그인' })).toBeNull()
  expect(screen.getByText('공용 시장 화면')).toBeTruthy()
})
