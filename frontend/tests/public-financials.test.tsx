import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'

const state = vi.hoisted(() => ({ financial: {} as Record<string, unknown>, company: {} as Record<string, unknown>, search: {} as Record<string, unknown>, calls: [] as unknown[][] }))
vi.mock('@/hooks/useFinancials', () => ({ useFinancials: (...args: unknown[]) => { state.calls.push(args); return state.financial } }))
vi.mock('@/hooks/useCompanySearch', () => ({ useCompany: () => state.company, useCompanySearch: () => state.search }))
vi.mock('@/components/shared/NextQuestions', () => ({ default: () => { throw new Error('private component mounted') } }))
const { PublicContent } = await import('../src/components/auth/PublicContent')
const ready = (data: unknown) => ({ data, error: null, isPending: false, isFetching: false, fetchStatus: 'idle', refetch: vi.fn() })
const financial = { periods: ['25.12'], rows: [{ account_nm: '매출액', values: ['100000000'], yoy: [null] }], key_metrics: {}, sj_div: 'IS', fs_div: 'CFS', period_type: 'annual' }
function Location() { const l = useLocation(); return <output data-testid="location">{l.pathname}{l.search}</output> }
function show(path = '/analyze/111111/financials') { return render(<MemoryRouter initialEntries={[path]}><PublicContent /><Location /></MemoryRouter>) }
afterEach(() => { cleanup(); state.calls = []; vi.clearAllMocks() })
function setup() {
  state.financial = ready(financial)
  state.company = ready({ corp_name: 'Fixture Corp', stock_code: '111111', corp_code: 'corp' })
  state.search = ready([{ corp_name: 'Fixture Corp', stock_code: '111111', corp_code: 'corp' }])
}
it('search selection, URL controls and return never mount private company helpers', () => {
  setup(); show('/financials?q=Fixture')
  fireEvent.click(screen.getByRole('link', { name: /Fixture Corp/ }))
  expect(screen.getByRole('heading', { name: /Fixture Corp.*재무/ })).toBeTruthy()
  expect(state.calls.at(-1)?.at(-1)).toEqual({ storedOnly: true })
  fireEvent.click(screen.getByRole('radio', { name: '분기' }))
  expect(screen.getByTestId('location').textContent).toContain('period=quarterly')
  fireEvent.click(screen.getByRole('link', { name: '기업 검색으로' }))
  expect(screen.getByRole('searchbox').getAttribute('value')).toBe('Fixture')
})
it('restores conditions and identifies OFS and BS point-in-time values', () => {
  setup(); state.financial = ready({ ...financial, fs_div: 'OFS', sj_div: 'BS' })
  show('/analyze/111111/financials?sj=BS&period=trailing&years=10&fs=CFS')
  expect(state.calls.at(-1)?.slice(0, 5)).toEqual(['111111', 'BS', 'trailing', 10, 'CFS'])
  expect(screen.getByText(/표시 기준:/).textContent).toContain('별도재무제표')
  expect(screen.getByText(/표시 기준:/).textContent).toContain('합산하지 않습니다')
})
it('renders empty and partial data without invented numbers', () => {
  setup(); state.financial = ready({ ...financial, periods: [], rows: [] }); const empty = show()
  expect(screen.getByText('선택한 조건으로 표시할 저장 재무 자료가 없습니다.')).toBeTruthy(); empty.unmount()
  state.financial = ready({ ...financial, rows: [{ ...financial.rows[0], values: [null] }] }); show()
  expect(screen.getByText(/일부 항목이 누락/)).toBeTruthy()
})
it('shows loading skeleton and a retryable error', () => {
  setup(); state.financial = { ...ready(undefined), isPending: true, fetchStatus: 'fetching' }; const loading = show()
  expect(screen.getByRole('status', { name: '데이터 불러오는 중' })).toBeTruthy(); loading.unmount()
  const retry = vi.fn(); state.financial = { ...ready(undefined), error: new Error('fixture unavailable'), refetch: retry }; show()
  fireEvent.click(screen.getByRole('button', { name: /다시|재시도/ })); expect(retry).toHaveBeenCalledOnce()
})
