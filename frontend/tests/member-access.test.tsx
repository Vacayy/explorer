// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { AccountControl, AccountPage, MemberAccessProvider } from '@/components/auth/MemberAccess'

const auth = vi.hoisted(() => ({ session: vi.fn(), logout: vi.fn() }))
vi.mock('@/api/auth', () => ({
  getMemberSession: auth.session,
  logoutMember: auth.logout,
  googleLoginUrl: () => '/api/auth/google/start',
}))
vi.mock('@/lib/memberReset', () => ({ clearMemberBrowserState: vi.fn(), leaveMemberSession: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><MemberAccessProvider enabled>
    <AccountControl /><AccountPage />
  </MemberAccessProvider></MemoryRouter></QueryClientProvider>)
}

it('offers Google login to an anonymous visitor', async () => {
  auth.session.mockResolvedValue({ authenticated: false, user: null, csrf_token: null, login_available: true })
  mount()
  expect(await screen.findByRole('link', { name: 'Google 로그인' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '계정 메뉴' })).toBeTruthy()
})

it('shows the member account and menu actions after sign-in', async () => {
  auth.session.mockResolvedValue({ authenticated: true, user: { id: 'test', role: 'operator' }, csrf_token: 'test', login_available: true })
  mount()
  expect(await screen.findByText('운영자 계정으로 로그인했습니다.')).toBeTruthy()
  fireEvent.pointerDown(screen.getByRole('button', { name: '계정 메뉴' }), { button: 0, ctrlKey: false })
  expect(await screen.findByRole('menuitem', { name: '마이페이지' })).toBeTruthy()
  auth.logout.mockResolvedValue({ ok: true })
  fireEvent.click(screen.getByRole('menuitem', { name: '로그아웃' }))
  await vi.waitFor(() => expect(auth.logout).toHaveBeenCalledWith('test'))
})
