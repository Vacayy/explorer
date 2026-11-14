import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { TooltipProvider } from '../src/components/ui/tooltip'
import { ApiError } from '../src/api/errors'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/lib/accessMode', () => ({ PUBLIC_ACCESS: true }))
vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))
const state = vi.hoisted(() => ({ data: undefined as unknown, isError: false, error: null as Error | null, refetch: vi.fn(), details: {} as Record<string, unknown> }))
vi.mock('@/hooks/useSectorView', () => ({ useUsIndustryMap: () => state, useUsSectorMarket: (ticker: string) => ({ ...state, data: state.details[ticker] }) }))
const { PublicContent } = await import('../src/components/auth/PublicContent')
const row = (ticker: string, name: string) => ({ ticker, name, full_name: name + ' ETF', parent: null,
  last: 100, last_date: '2026-11-13', chg_1d: 1, ret_1m: 2, ret_3m: null, chg_1w: 3,
  rs_long: 80, rs_short: 60, trail: [], coverage: null, series: [100, 101, 102] })
function show(path = '/industry?market=us&rank=cov') {
  return render(<MemoryRouter initialEntries={[path]}><TooltipProvider><PublicContent /></TooltipProvider></MemoryRouter>)
}
afterEach(() => { cleanup(); state.data = undefined; state.isError = false; state.error = null; state.details = {}; vi.clearAllMocks() })

it('renders public ETF map, filters names and rejects personal coverage sorting', () => {
  state.data = { as_of: '2026-11-13', spy: [100, 101, 102], sectors: [row('XLK', '기술'), row('XLF', '금융')] }
  const view = show()
  expect(screen.getByRole('img', { name: '미국 섹터 상대강도 지도' })).toBeTruthy()
  expect(view.container.textContent).not.toContain('내 커버리지')
  expect(view.container.textContent).toContain('장기 RS 순')
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'XLK' } })
  expect(view.container.querySelectorAll('a[aria-label]')).toHaveLength(1)
  const link = view.container.querySelector('a[aria-label]')!
  expect(link.getAttribute('href')).toBe('/industry/us/XLK')
  fireEvent.click(link)
  expect(screen.getByRole('heading', { name: 'XLK' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '섹터 지도 · 미국' }).getAttribute('href')).toBe('/industry?market=us')
})

it('shows loading, empty and retry states without mounting personal pages', () => {
  const loading = show()
  expect(screen.getByText('미국 산업 지도')).toBeTruthy()
  expect(loading.container.textContent).not.toContain('내 커버리지')
  loading.unmount()
  state.data = { as_of: null, spy: [], sectors: [] }
  const empty = show()
  expect(screen.getAllByText('섹터 ETF 시세가 쌓이면 나타납니다.').length).toBeGreaterThan(0)
  empty.unmount()
  state.data = undefined; state.isError = true
  show()
  expect(screen.getByText('미국 섹터 상대강도를 불러오지 못했습니다')).toBeTruthy()
  fireEvent.click(screen.getAllByRole('button', { name: /다시|재시도/ })[0])
  expect(state.refetch).toHaveBeenCalled()
})

const detail = (ticker: string) => {
  const { coverage: _coverage, ...market } = row(ticker, ticker === 'SMH' ? '반도체' : '기술')
  return { ...market, as_of: '2026-11-13', zone: '주도', parent: ticker === 'SMH' ? 'XLK' : null,
    parent_name: ticker === 'SMH' ? '기술' : null,
    series: [{ d: '2026-10-01', v: 100, k: 100 }, { d: '2026-11-13', v: 110, k: 105 }],
    siblings: [{ ticker: 'XLK', name: '기술', parent: null, ret_1m: 2, ret_3m: 3, rs_long: 80, rs_short: 60 }] }
}

it('opens public chart, changes period and navigates parent without private tabs', () => {
  state.details = { SMH: detail('SMH'), XLK: detail('XLK') }
  const view = show('/industry/us/SMH?tab=stocks')
  expect(screen.getByRole('heading', { name: '반도체' })).toBeTruthy()
  expect(screen.getByRole('img', { name: /SMH와 SPY/ })).toBeTruthy()
  expect(screen.queryByRole('tab')).toBeNull()
  expect(view.container.textContent).not.toContain('내 커버리지')
  expect(view.container.textContent).not.toContain('주요 자료')
  fireEvent.click(screen.getByText('3개월', { exact: true }))
  expect(screen.getByRole('img', { name: 'SMH와 SPY, 3개월 전 = 100' })).toBeTruthy()
  fireEvent.click(screen.getByRole('navigation', { name: '위치' }).querySelector('a[href="/industry/us/XLK"]')!)
  expect(screen.getByRole('heading', { name: '기술' })).toBeTruthy()
})

it('keeps empty price and missing ticker states distinct', () => {
  state.details = { XLK: { ...detail('XLK'), series: [], last: null } }
  const empty = show('/industry/us/XLK')
  expect(screen.getByText('ETF 시세가 쌓이면 나타납니다.')).toBeTruthy()
  empty.unmount()
  state.isError = true; state.error = new ApiError('missing', 404)
  show('/industry/us/UNKNOWN')
  expect(screen.getByRole('status').textContent).toContain('없는 미국 섹터')
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.getByRole('link', { name: '섹터 지도 · 미국' })).toBeTruthy()
})
