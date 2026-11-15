import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { PublicMacroResponse } from '@/types'

const state = vi.hoisted(() => ({ query: {} as Record<string, unknown> }))
vi.mock('@/hooks/usePublicMacro', () => ({ usePublicMacro: () => state.query }))
vi.mock('@/hooks/useMacro', () => ({ useMacro: () => { throw new Error('private macro mounted') } }))
const { PublicMacroPage } = await import('@/components/home/PublicMacroPage')
const data: PublicMacroResponse = {
  as_of: '2026-11-14',
  items: [{ key: 'us10y', label: '미국 10년 금리', group: 'rates', group_label: '금리·달러', fmt: 'pct', as_of: '2026-11-14', value: 4.25, change_pct: 6.25,
    series: [4, 4.1, 4.2, 4.3, 4.2, 4.25], dated_series: [['2026-11-06',4],['2026-11-09',4.1],['2026-11-10',4.2],['2026-11-12',4.3],['2026-11-13',4.2],['2026-11-14',4.25]],
    comparison_date: '2026-11-06', comparison_observations: 5,
    sources: [{ series_id: 'RIFLGFCY10_N.B', publisher: 'Board of Governors of the Federal Reserve System', url: 'https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip', as_of: '2026-11-14' }] }],
  coverage: [{ key: 'us10y', label: '미국 10년 금리', status: 'available' }, { key: 'us2y', label: '미국 2년 금리', status: 'missing' }, { key: 'm2', label: 'M2', status: 'source_review_pending' }, { key: 'invalid', label: '검증 지표', status: 'invalid' }],
}
const ready = (value: unknown = data) => ({ data: value, error: null, isPending: false, isFetching: false, fetchStatus: 'idle', refetch: vi.fn() })
function show() { return render(<MemoryRouter initialEntries={['/home/macro']}><PublicMacroPage /></MemoryRouter>) }
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('shows numeric observations, real dates, comparison count and source attribution without private macro hooks', () => {
  state.query = ready(); show()
  const item = screen.getByRole('region', { name: '미국 10년 금리' })
  expect(within(item).getByText('4.25%')).toBeTruthy()
  expect(within(item).getByText('관측일 2026-11-14')).toBeTruthy()
  expect(within(item).getByText(/5개 관측 전 대비/).textContent).toContain('+6.25%')
  expect(within(item).getByText(/비교 관측일/).textContent).toContain('2026-11-06')
  expect(within(item).getByText(/달력상 5일 전을 뜻하지 않습니다/)).toBeTruthy()
  const source = within(item).getByRole('link', { name: 'Board of Governors of the Federal Reserve System · RIFLGFCY10_N.B' })
  expect(source.getAttribute('href')).toBe('https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip')
  expect(source.getAttribute('rel')).toBe('noopener noreferrer')
  expect(within(item).getByText(/원천 관측일/).textContent).toContain('2026-11-14')
  expect(screen.getByText('저장된 관측값 없음')).toBeTruthy()
  expect(screen.getByText('출처·공개 범위 검토 중')).toBeTruthy()
  expect(screen.getByText('저장 자료 검증 필요')).toBeTruthy()
  expect(screen.getByText(/데이터가 없다는 뜻이 아닙니다/)).toBeTruthy()
  expect(screen.getByText(/지표마다 관측 주기와 최신 날짜가 다릅니다/)).toBeTruthy()
})
it('retains each component source date for mixed-frequency observations', () => {
  state.query = ready({ ...data, items: [{ ...data.items[0], key: 'net_liq', label: '순유동성', fmt: 'trillion_b', sources: [
    { series_id: 'RESPPMA_N.WW', publisher: 'Board of Governors of the Federal Reserve System', url: 'https://www.federalreserve.gov/releases/h41/data/FRB_h41_xml.zip', as_of: '2026-11-11' },
    { series_id: 'RESPPLLDT_XAW_N.WW', publisher: 'Board of Governors of the Federal Reserve System', url: 'https://www.federalreserve.gov/releases/h41/data/FRB_h41_xml.zip', as_of: '2026-11-12' },
    { series_id: 'overnight_treasury_rrp', publisher: 'Federal Reserve Bank of New York', url: 'https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/200.json', as_of: '2026-11-14' },
  ] }] }); show()
  expect(screen.getByText(/원천 관측일 2026-11-11/)).toBeTruthy()
  expect(screen.getByText(/원천 관측일 2026-11-14/)).toBeTruthy()
  expect(screen.getByText(/원천 관측일 2026-11-12/)).toBeTruthy()
  expect(screen.getByText(/Explorer가 계산한 참고값이며 원기관의 공식 지표가 아닙니다/)).toBeTruthy()
  expect(screen.getByText(/관측일 사이에는 직전 값을 유지/).textContent).toContain('TGA는 주평균')
  expect(screen.getByText(/© 2026 Federal Reserve Bank of New York/)).toBeTruthy()
  expect(screen.getByText('Explorer의 계산·표시는 원기관의 보증을 뜻하지 않습니다.')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Federal Reserve Bank of New York 데이터 이용 조건' }).getAttribute('href')).toBe('https://www.newyorkfed.org/privacy/termsofuse')
})
it('distinguishes empty observations and insufficient comparison inputs', () => {
  state.query = ready({ ...data, items: [] }); const empty = show()
  expect(screen.getByText(/현재 표시할 공개 관측값이 없습니다/)).toBeTruthy()
  expect(screen.getByText('출처·공개 범위 검토 중')).toBeTruthy(); empty.unmount()
  state.query = ready({ ...data, items: [{ ...data.items[0], series: [4.25], dated_series: [['2026-11-14',4.25]], change_pct: null, comparison_date: null }] }); show()
  expect(screen.getByText('추이를 표시할 관측값이 부족합니다.')).toBeTruthy()
  expect(screen.getByText(/변화율을 표시하지 않습니다/)).toBeTruthy()
  expect(screen.getByText(/비교 관측일 자료 부족/)).toBeTruthy()
})
it('shows loading and retryable errors, preserving data after a refresh failure', () => {
  state.query = { ...ready(), data: undefined, isPending: true, fetchStatus: 'fetching' }; const loading = show()
  expect(screen.getByRole('status', { name: '데이터 불러오는 중' })).toBeTruthy(); loading.unmount()
  state.query = { ...ready(), data: undefined, error: new Error('failed') }; const failed = show()
  fireEvent.click(screen.getByRole('button', { name: /다시|재시도/ })); expect(state.query.refetch).toHaveBeenCalledOnce(); failed.unmount()
  state.query = { ...ready(), error: new Error('failed') }; show()
  expect(screen.getByText(/이전 결과를 표시합니다/)).toBeTruthy()
  expect(screen.getByText('4.25%')).toBeTruthy()
})
