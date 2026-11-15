import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
const state = vi.hoisted(() => ({ access: { status: 'member', session: { user: { id: 'A' } }, retry: vi.fn() }, list: {} as Record<string, unknown>, evaluation: {} as Record<string, unknown>, options: {} as Record<string, unknown>, save: { mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false, error: null }, remove: { mutate: vi.fn(), reset: vi.fn(), isPending: false, error: null }, read: vi.fn() }))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => state.access }))
vi.mock('@/hooks/useMemberPrinciples', () => ({
  useMemberPrinciples: () => { state.read(); return state.list }, useMemberPrincipleState: () => state.evaluation,
  useMemberPrincipleOptions: () => state.options, useSaveMemberPrinciple: () => state.save, useDeleteMemberPrinciple: () => state.remove,
}))
const { MemberPrinciplesPage } = await import('../src/components/portfolio/MemberPrinciplesPage')
const ready = (data: unknown) => ({ data, error: null, isPending: false, isFetching: false, fetchStatus: 'idle', refetch: vi.fn() })
function setup() {
  state.access.status = 'member'; state.access.session.user.id = 'A'; state.save.isError = false
  state.list = ready([]); state.options = ready([{ type: 'max_weight', label: '보유 비중 상한', parameter: 'pct', minimum: 1, maximum: 100 }])
  state.evaluation = ready({ as_of: null, price_dates: [], rules: 0, coverage: [], items: [], notifications_enabled: false })
}
function show() { return render(<MemoryRouter><MemberPrinciplesPage /></MemoryRouter>) }
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('requires login before mounting member readers', () => {
  setup(); state.access.status = 'anonymous'; show()
  expect(screen.getByRole('link', { name: 'Google 로그인' }).getAttribute('href')).toContain('portfolio')
  expect(state.read).not.toHaveBeenCalled()
})
it('saves explicitly confirmed rules and retains input on failed save', () => {
  setup(); state.save.isError = true; show()
  fireEvent.click(screen.getByRole('button', { name: '원칙 추가' }))
  fireEvent.change(screen.getByLabelText('원칙 원문'), { target: { value: '개인 원칙 CANARY' } })
  fireEvent.click(screen.getByRole('button', { name: '수치 규칙 추가' }))
  fireEvent.change(screen.getByLabelText('규칙 1 기준값'), { target: { value: '25' } })
  fireEvent.click(screen.getByRole('button', { name: '확인한 원칙 저장' }))
  expect(state.save.mutate.mock.calls[0][0]).toEqual({ id: undefined, body: { text: '개인 원칙 CANARY', rules: [{ type: 'max_weight', params: { pct: 25 } }], notes: [] } })
  expect((screen.getByLabelText('원칙 원문') as HTMLTextAreaElement).value).toBe('개인 원칙 CANARY')
  expect(screen.getByRole('alert').textContent).toContain('입력 내용은 유지')
})
it('clears editor when account changes and confirms deletion', () => {
  setup(); const view = show()
  fireEvent.click(screen.getByRole('button', { name: '원칙 추가' }))
  fireEvent.change(screen.getByLabelText('원칙 원문'), { target: { value: 'A PRIVATE CANARY' } })
  state.access.session.user.id = 'B'; view.rerender(<MemoryRouter><MemberPrinciplesPage /></MemoryRouter>)
  expect(screen.queryByLabelText('원칙 원문')).toBeNull()
  state.list = ready([{ id: 7, text: 'B 원칙', rules: [], notes: ['참고 원칙'], created_at: '2026-01-01' }])
  view.rerender(<MemoryRouter><MemberPrinciplesPage /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '삭제' }))
  expect(state.remove.mutate).not.toHaveBeenCalled()
  fireEvent.click(screen.getAllByRole('button', { name: '삭제' }).at(-1)!)
  expect(state.remove.mutate).toHaveBeenCalledWith(7)
})
it('does not equate missing coverage with compliance or promise notifications', () => {
  setup(); state.evaluation = ready({ as_of: '2026-01-01', price_dates: ['2025-12-20', '2026-01-01'], rules: 1, coverage: [{ principle_id: 1, rule_index: 0, rule: '비중', status: 'unavailable', reason: 'Some holdings have no stored price' }], items: [], notifications_enabled: false })
  show(); expect(screen.getByText(/평가하지 못한 항목은 준수 여부를 판단할 수 없습니다/)).toBeTruthy()
  expect(screen.getByText(/알림은 발송하지 않습니다/)).toBeTruthy()
  expect(screen.getByText(/시세가 없는 보유 종목/)).toBeTruthy()
  expect(screen.getByText(/종목마다 시세 갱신 시점/).textContent).toContain('2025-12-20, 2026-01-01')
})
