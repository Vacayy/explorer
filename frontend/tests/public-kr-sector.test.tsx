import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { KrSectorMarket } from '@/types'

const state = vi.hoisted(() => ({ query: {} as Record<string, unknown>, calls: [] as string[] }))
vi.mock('@/hooks/useSectorView', () => ({
  useKrSectorMarket: (sector: string) => { state.calls.push(sector); return state.query },
  useSectorDetail: () => { throw new Error('private detail mounted') },
  useFollowedEntities: () => { throw new Error('private follows mounted') },
  useSectorPeerList: () => { throw new Error('private peers mounted') },
}))
const { PublicKrSectorPage } = await import('@/components/industry/PublicKrSectorPage')
beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})
const stocks = Array.from({ length: 25 }, (_, i) => ({ stock_code: String(100000 + i), corp_name: `공개종목${i + 1}`, market_cap: 1e12, weight: 4, chg_1d: 1, ret_1m: 2, rs_long: 50, rs_short: 60 }))
const data: KrSectorMarket = {
  as_of: '2026-11-01', name: '반도체·전자부품', benchmark: { kind: 'etf', ticker: '091160', name: 'KODEX 반도체', tracks: 'KRX 반도체', note: null },
  last: 110, last_date: '2026-10-31', chg_1d: 1, ret_1m: 2, ret_3m: 4, rs_long: 50, rs_short: 60, chg_5d: 2,
  trail: [{ weeks_ago: 1, rs_long: 40, rs_short: 50 }], market_cap: 25e12, stocks: 25,
  series: Array.from({ length: 90 }, (_, i) => ({ d: new Date(Date.UTC(2026, 7, 1) + i * 86400000).toISOString().slice(0, 10), v: 100 + i, k: 50 + i })),
  top_weights: stocks.slice(0, 8), constituents: stocks,
}
function ready(value: unknown = data) { return { data: value, error: null, isError: false, isPending: false, isFetching: false, fetchStatus: 'idle', refetch: vi.fn() } }
function Location() { const l = useLocation(); return <output aria-label="URL">{l.pathname}{l.search}</output> }
function show(search = '?range=3m&map_query=%3Fmarket%3Dkr%26q%3D%25EB%25B0%2598%25EB%258F%2584%25EC%25B2%25B4') {
  return render(<MemoryRouter initialEntries={['/industry/반도체·전자부품' + search]}><TooltipProvider><PublicKrSectorPage sector="반도체·전자부품" /><Location /></TooltipProvider></MemoryRouter>)
}
afterEach(() => { cleanup(); state.calls = []; vi.clearAllMocks() })
it('reuses price chart and paged constituents with full return context and no private hooks', () => {
  state.query = ready(); show()
  expect(screen.getByRole('img', { name: '대표지수와 코스피, 3개월 전 = 100' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '한국 산업 지도' }).getAttribute('href')).toBe('/industry?market=kr&q=%EB%B0%98%EB%8F%84%EC%B2%B4')
  expect(screen.getByText(/구성 종목 기준일/).textContent).toContain('2026-11-01 · 대표지수 시세일 2026-10-31')
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('row')).toHaveLength(21)
  fireEvent.click(screen.getByRole('link', { name: '2페이지' }))
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(6)
  const href = screen.getByRole('link', { name: '공개종목21' }).getAttribute('href')!
  const params = new URL(href, 'https://local.test').searchParams
  expect(params.get('sector')).toBe(data.name)
  expect(params.get('sector_query')).toContain('page=2')
  expect(params.get('sector_query')).toContain('range=3m')
  expect(params.get('sector_query')).toContain('map_query=')
  expect(new Set(state.calls)).toEqual(new Set([data.name]))
})
it('shows missing inputs, empty chart and constituents without invented values', () => {
  state.query = ready({ ...data, last: null, rs_short: null, series: [], constituents: [], top_weights: [] }); show()
  expect(screen.getByText(/일부 시세·상대강도/)).toBeTruthy()
  expect(screen.getByText('대표지수 시세가 쌓이면 나타납니다.')).toBeTruthy()
  expect(screen.getByText('이 섹터로 분류된 종목이 없습니다.')).toBeTruthy()
})
it('shows loading, retries failures, and retains the successful snapshot on refresh error', () => {
  state.query = { ...ready(undefined), data: undefined, isPending: true, fetchStatus: 'fetching' }
  const pending = show(); expect(screen.getByRole('status', { name: '데이터 불러오는 중' })).toBeTruthy(); pending.unmount()
  state.query = { ...ready(), data: undefined, error: new Error('unavailable'), isError: true }
  const failed = show(); fireEvent.click(screen.getByRole('button', { name: /다시|재시도/ })); expect(state.query.refetch).toHaveBeenCalledOnce(); failed.unmount()
  state.query = { ...ready(), error: new Error('unavailable'), isError: true }; show()
  expect(screen.getByText(/이전 결과를 표시합니다/)).toBeTruthy()
  expect(screen.getByRole('img')).toBeTruthy()
  expect(screen.getByRole('table')).toBeTruthy()
})
it('ignores an external map-return value', () => {
  state.query = ready(); show('?map_query=https%3A%2F%2Fevil.test')
  expect(screen.getByRole('link', { name: '한국 산업 지도' }).getAttribute('href')).toBe('/industry')
})

it('distinguishes an absent sector from a retryable server failure', () => {
  state.query = { ...ready(), data: undefined, error: { response: { status: 404 } }, isError: true }; show()
  expect(screen.getByText(/이 섹터의 공개 시장 자료가 없습니다/)).toBeTruthy()
  expect(screen.queryByRole('table')).toBeNull()
  expect(screen.getByRole('link', { name: '한국 산업 지도' })).toBeTruthy()
})
