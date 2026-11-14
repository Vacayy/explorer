import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ApiError } from '@/api/errors'
import type { PortfolioSummary, PortfolioTransaction } from '@/types'

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver

const fixture = vi.hoisted(() => ({ access: { status: 'member', session: { user: { id: 'A' } }, retry: vi.fn() },
  summary: { error: null as Error | null, data: undefined as PortfolioSummary | undefined, isError: false, isPending: false, refetch: vi.fn() },
  history: { data: [], isError: false, isPending: false, refetch: vi.fn() },
  transactions: { data: [] as PortfolioTransaction[], isError: false, isPending: false, refetch: vi.fn() },
  add: { mutate: vi.fn(), reset: vi.fn(), isPending: false, error: null },
  remove: { reset: vi.fn(), mutate: vi.fn(), isPending: false, isError: false, error: null },
  read: vi.fn(),
}))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => fixture.access }))
vi.mock('@/api/auth', () => ({ googleLoginUrl: (path: string) => '/api/auth/google/start?return_to=' + encodeURIComponent(path) }))
vi.mock('@/hooks/useMemberPortfolio', () => ({
  useMemberPortfolio: () => { fixture.read(); return fixture.summary },
  useMemberPortfolioHistory: () => fixture.history,
  useMemberPortfolioTransactions: () => fixture.transactions,
  useAddMemberPortfolioTransaction: () => fixture.add,
  useDeleteMemberPortfolioTransaction: () => fixture.remove,
  useMemberPortfolioCompanies: () => ({ data: [], isFetching: false, isError: false }),
}))
vi.mock('@/components/charts/AreaSeriesChart', () => ({ default: () => <div>수익률 차트</div> }))
vi.mock('@/hooks/usePortfolio', () => ({ useAddPortfolioTransaction: () => { throw Error('Private hook mounted') } }))
const { PublicContent } = await import('@/components/auth/PublicContent')
function show() { return render(<MemoryRouter initialEntries={['/portfolio']}><PublicContent /></MemoryRouter>) }
afterEach(() => { cleanup(); vi.clearAllMocks(); fixture.access.status = 'member'; fixture.summary.data = undefined; fixture.summary.isError = false; fixture.summary.error = null; fixture.summary.isPending = false; fixture.transactions.data = [] })

it('shows login, loading, and login failure without mounting portfolio hooks', () => {
  fixture.access.status = 'anonymous'; const view = show()
  expect(screen.getByRole('link', { name: 'Google 로그인' }).getAttribute('href')).toContain('return_to=%2Fportfolio')
  expect(fixture.read).not.toHaveBeenCalled()
  fixture.access.status = 'loading'; view.rerender(<MemoryRouter><PublicContent /></MemoryRouter>)
  // Same initial router location remains /portfolio.
  expect(screen.getByRole('status').textContent).toContain('계정 확인')
  fixture.access.status = 'error'; view.rerender(<MemoryRouter><PublicContent /></MemoryRouter>)
  expect(screen.getByText('로그인 상태를 확인할 수 없습니다.')).toBeTruthy()
  expect(fixture.read).not.toHaveBeenCalled()
})

it('renders empty member portfolio and reuses the full input form without private hooks', () => {
  fixture.summary.data = { as_of: null, total_return_pct: null, day_return_pct: null, cash_weight_pct: null,
    holdings: [], quoted_at: null, realized_pct: null, unrealized_pct: null, closed: [] }
  show()
  expect(screen.getByText(/아직 기록된 거래가 없습니다/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '거래 입력' }))
  fireEvent.click(screen.getByRole('radio', { name: '입금' }))
  fireEvent.change(screen.getByLabelText('입금액 (만원)'), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: '기록' }))
  expect(fixture.add.mutate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'deposit', amount: 20000 }), expect.any(Object))
  expect(screen.queryByText('시세 갱신')).toBeNull()
})

it('shows only price and ratio fields; deletion uses the selected transaction ID', () => {
  fixture.summary.data = { as_of: '2026-01-01', total_return_pct: 3, day_return_pct: null, cash_weight_pct: 50,
    holdings: [{ code: 'AAAAAA', name: '가나', weight_pct: 50, return_pct: 3, day_change_pct: null, avg_price: 10, last_close: null, last_date: null, entry_date: '2026-01-01' }],
    quoted_at: null, realized_pct: null, unrealized_pct: null, closed: [] }
  fixture.transactions.data = [{ id: 8, trade_date: '2026-01-01', kind: 'buy', stock_code: 'AAAAAA', name: '가나', price: 10 }]
  show()
  expect(screen.getByText('일부 종목의 저장된 시세가 없습니다.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '2026-01-01 매수 삭제' }))
  expect(fixture.remove.mutate).toHaveBeenCalledExactlyOnceWith(8)
  expect(screen.queryByText('운용 원칙')).toBeNull()
  expect(screen.queryByText('알림 이력')).toBeNull()
})

it('hides prior summary on an access/read error and exposes retry', () => {
  fixture.summary.data = { as_of: null, total_return_pct: 88, day_return_pct: null, cash_weight_pct: 100, holdings: [], closed: [], quoted_at: null, realized_pct: null, unrealized_pct: null }
  fixture.summary.isError = true; show()
  expect(screen.queryByText('+88.0%')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /다시/ }))
  expect(fixture.summary.refetch).toHaveBeenCalledOnce()
})

it('hides all cached member sections after an authorization failure', () => {
  fixture.summary.error = new ApiError('Access denied', 403); fixture.summary.isError = true
  fixture.transactions.data = [{ id: 8, trade_date: '2026-01-01', kind: 'buy', stock_code: 'AAAAAA', name: 'private cached name', price: 10 }]
  show()
  expect(screen.queryByText('private cached name')).toBeNull()
  expect(screen.queryByRole('button', { name: '거래 입력' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /다시/ }))
  expect(fixture.access.retry).toHaveBeenCalledOnce()
  expect(fixture.transactions.refetch).toHaveBeenCalledOnce()
})
