import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const state = vi.hoisted(() => ({
  status: 'anonymous', retry: vi.fn(), trial: vi.fn(),
  session: { authenticated: false, user: null, csrf_token: null, login_available: false, chat_available: false },
}))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => state }))
vi.mock('@/hooks/useTrialChat', () => ({ useTrialChat: () => { state.trial(); throw Error('Chat must not mount') } }))
const { MemberSavedPage } = await import('@/components/follow/MemberSavedPage')
const { MemberPrinciplesPage } = await import('@/components/portfolio/MemberPrinciplesPage')
const { MemberPortfolioPage } = await import('@/components/portfolio/MemberPortfolioPage')
const { MemberDocumentSaveButton } = await import('@/components/shared/MemberDocumentSaveButton')
const { PublicTrialChatPage } = await import('@/components/chat/PublicTrialChatPage')
beforeEach(() => { state.status = 'anonymous' })
afterEach(() => { cleanup(); vi.clearAllMocks() })

it.each([MemberSavedPage, MemberPrinciplesPage, MemberPortfolioPage, () => <MemberDocumentSaveButton docId={1} />])(
  'replaces login links without mounting member queries', Component => {
    render(<MemoryRouter><Component /></MemoryRouter>)
    expect(screen.getByText('로그인 준비 중')).toBeTruthy()
    expect(document.querySelector('a[href*="/api/auth/google/start"]')).toBeNull()
  },
)
it('does not mount trial chat or fetch document selection in read-only mode', () => {
  render(<MemoryRouter><PublicTrialChatPage /></MemoryRouter>)
  expect(screen.getByRole('heading', { name: '채팅 준비 중' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '공개 자료 보기' }).getAttribute('href')).toBe('/feed')
  expect(state.trial).not.toHaveBeenCalled()
  expect(screen.queryByLabelText('질문')).toBeNull()
})
it('keeps failed session checks distinct from confirmed unavailable chat', () => {
  state.status = 'error'
  render(<MemoryRouter><PublicTrialChatPage /></MemoryRouter>)
  expect(screen.queryByText('채팅 준비 중')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /다시 시도/ }))
  expect(state.retry).toHaveBeenCalledOnce()
  expect(state.trial).not.toHaveBeenCalled()
})
it('waits for confirmed session availability before mounting trial chat', () => {
  state.status = 'loading'
  render(<MemoryRouter><PublicTrialChatPage /></MemoryRouter>)
  expect(screen.getByRole('status').textContent).toBe('계정 확인 중…')
  expect(state.trial).not.toHaveBeenCalled()
})
