import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import api from '@/api/client'
import type { PublicTradeResponse, PublicTradeRow } from '@/types'

const state = vi.hoisted(() => ({ query: {} as Record<string, unknown>, calls: [] as unknown[][], chart: {} as Record<string, unknown> }))
vi.mock('@/hooks/usePublicTrade', () => ({ usePublicTrade: (...args: unknown[]) => { state.calls.push(args); return state.query } }))
vi.mock('@/hooks/useTrade', () => ({ useTradeFollows: () => { throw new Error('private follows') }, useTradeGrid: () => { throw new Error('private grid') }, useTradeHighlights: () => { throw new Error('private highlights') } }))
vi.mock('@/lib/usage', () => ({ track: () => { throw new Error('private telemetry') } }))
vi.mock('@/components/industry/MonitorWall', async importOriginal => {
  const actual = await importOriginal<typeof import('@/components/industry/MonitorWall')>()
  return { ...actual, BigChart: (props: Parameters<typeof actual.BigChart>[0]) => { state.chart = props; return <actual.BigChart {...props} /> } }
})
const { MiniBars } = await import('@/components/industry/MonitorWall')
const { PublicContent } = await import('@/components/auth/PublicContent')
const actualHook = await vi.importActual<typeof import('@/hooks/usePublicTrade')>('@/hooks/usePublicTrade')
beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver })
const item: PublicTradeRow = {
  hs_code: '8542', item_name: '반도체', group_label: '전자', nested_in: null, fetched_at: '2026-11-15T01:00:00', missing: false,
  metrics: { export_usd: 100000000, import_usd: 50000000, balance_usd: 50000000, ma12: null, period: '2026-10', value: 100000000, mom: .1, yoy: .2, qoq: null, yoy3m: .3, z: 1, flag: 'none', reason: '관측 기준', delta_usd: 1000, contribution: null },
  series: [{ export_usd: 80000000, import_usd: 50000000, balance_usd: 30000000, ma12: null, period: '2026-08', value: 80000000, mom: null, yoy: .1, qoq: null, yoy3m: null }, { export_usd: null, import_usd: null, balance_usd: null, ma12: null, period: '2026-09', value: null, mom: null, yoy: null, qoq: null, yoy3m: null }, { export_usd: 100000000, import_usd: 50000000, balance_usd: 50000000, ma12: null, period: '2026-10', value: 100000000, mom: .1, yoy: .2, qoq: null, yoy3m: .3 }],
}
const data: PublicTradeResponse = {
  flow: 'export', period: '2026-10', latest_period: '2026-10', periods: ['2026-10','2026-09'], months: 60, unit: 'USD', valuation: 'FOB',
  source: '관세청', source_url: 'https://www.data.go.kr/data/15101609/openapi.do', note: '저장 통계는 정정될 수 있습니다.', fetched_at: '2026-11-15T01:00:00', empty: false, partial: true,
  rows: [item, { ...item, hs_code: '8703', item_name: '승용차', group_label: '자동차', missing: true, metrics: { ...item.metrics, export_usd: null, import_usd: null, balance_usd: null, value: null, mom: null, yoy: null, yoy3m: null }, series: item.series.map(point => ({ ...point, export_usd: null, import_usd: null, balance_usd: null, value: null, yoy: null })) }],
  total: { value: 100000000, observed_count: 1, total_count: 2, partial: true },
  groups: [{ group_label: '전자', value: 100000000, observed_count: 1, total_count: 1, partial: false }, { group_label: '자동차', value: null, observed_count: 0, total_count: 1, partial: true }],
}
const ready = (value: unknown = data) => ({ data: value, error: null, isPending: false, isFetching: false, fetchStatus: 'idle', refetch: vi.fn() })
function Location() { const location = useLocation(); return <output aria-label="URL">{location.pathname}{location.search}</output> }
function show(path = '/follow/trade') { return render(<MemoryRouter initialEntries={[path]}><PublicContent /><Location /></MemoryRouter>) }
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); state.calls = []; state.chart = {} })
it('keeps flow, month, search and group through detail and back without private queries', () => {
  state.query = ready(); show('/follow/trade?flow=import&months=24&period=2026-09&q=반도체&group=전자')
  expect(state.calls.at(-1)).toEqual(['import','2026-09',24])
  expect(screen.queryByRole('button', { name: '승용차 상세 열기' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '반도체 상세 열기' }))
  expect(screen.getByRole('region', { name: '공개 품목 상세' })).toBeTruthy()
  expect(screen.getByLabelText('URL').textContent).toContain('/follow/trade/8542')
  expect(screen.getByLabelText('URL').textContent).toContain('months=24')
  fireEvent.click(screen.getByRole('link', { name: '품목 목록으로' }))
  expect(screen.getByRole('searchbox').getAttribute('value')).toBe('반도체')
  expect(screen.queryByRole('button', { name: '승용차 상세 열기' })).toBeNull()
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: '없는품목' } })
  expect(screen.getByText('검색·그룹 조건에 맞는 공개 품목이 없습니다.')).toBeTruthy()
})
it('shows catalog partial totals, source/valuation and preserves null chart gaps and server ratios', () => {
  state.query = ready(); const list = show()
  expect(screen.getByText(/국가 전체 무역 총액이 아닙니다/).textContent).toContain('2개 중 1개')
  expect(screen.getByText(/전체 합계로 해석할 수 없습니다/)).toBeTruthy()
  expect(screen.getByRole('link', { name: /품목별 수출입실적 원출처/ }).getAttribute('href')).toBe(data.source_url)
  expect(screen.getByText(/수출은 FOB, 수입은 CIF/)).toBeTruthy()
  list.unmount(); show('/follow/trade/8542')
  expect(state.chart.connectNulls).toBe(false)
  expect(state.chart.data).toEqual([{ period: '2026-08', v: 80000000, yoy: 10 }, { period: '2026-09', v: null, yoy: null }, { period: '2026-10', v: 100000000, yoy: 20 }])
  const detail = screen.getByRole('region', { name: '공개 품목 상세' })
  expect(within(detail).getByText('+10.0%')).toBeTruthy()
  expect(within(detail).getByText('+30.0%')).toBeTruthy()
  expect(within(detail).getByText(/품목 저장 시점/).textContent).toContain(item.fetched_at)
})
it('never substitutes another month for missing selected values and keeps flow controls in the URL', () => {
  state.query = ready(); show('/follow/trade/8703')
  expect(screen.getByText(/다른 달의 값으로 대신하지 않습니다/)).toBeTruthy()
  expect((state.chart.data as { v: number | null }[]).every(point => point.v === null)).toBe(true)
  fireEvent.click(screen.getByRole('radio', { name: '수입' }))
  expect(state.calls.at(-1)?.[0]).toBe('import')
  fireEvent.click(screen.getByRole('radio', { name: '2년' }))
  expect(state.calls.at(-1)?.[2]).toBe(24)
  fireEvent.change(screen.getByLabelText('통계월'), { target: { value: '2026-09' } })
  expect(state.calls.at(-1)).toEqual(['import','2026-09',24])
  fireEvent.click(screen.getByRole('button', { name: '최신 통계월' }))
  expect(state.calls.at(-1)?.[1]).toBe(null)
})
it('has loading/empty/unknown-item states and hides cached data on failed verification', () => {
  state.query = { ...ready(undefined), data: undefined, isPending: true, fetchStatus: 'fetching' }; const loading = show()
  expect(screen.getByRole('status', { name: '데이터 불러오는 중' })).toBeTruthy(); loading.unmount()
  state.query = ready({ ...data, rows: [], empty: true, period: null }); const empty = show()
  expect(screen.getByText('저장된 공개 품목 통계가 없습니다.')).toBeTruthy(); empty.unmount()
  state.query = ready(); const missing = show('/follow/trade/unknown')
  expect(screen.getByText('공개 카탈로그에 없는 품목입니다.')).toBeTruthy(); missing.unmount()
  state.query = { ...ready(), error: { response: { status: 400 } } }; show()
  expect(screen.queryByRole('button', { name: '반도체 상세 열기' })).toBeNull()
  expect(screen.queryByRole('region', { name: '공개 카탈로그 집계' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' })); expect(state.query.refetch).toHaveBeenCalledOnce()
})
it('real hook requests only the fixed public route and scopes query cache to its selection', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function Harness() { const query = actualHook.usePublicTrade('import','2026-09',24); return <span>{query.data ? 'ready' : 'loading'}</span> }
  const view = render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
  await screen.findByText('ready')
  expect(get).toHaveBeenCalledTimes(1)
  expect(get.mock.calls[0][0]).toBe('/api/public/trade')
  expect(get.mock.calls[0][1]?.params).toEqual({ flow: 'import', period: '2026-09', months: 24 })
  await waitFor(() => expect(client.getQueryCache().getAll()[0].queryKey).toEqual(['public','trade','import','2026-09',24]))
  view.unmount(); client.clear()
})

it('breaks public moving-average lines at missing months while retaining private defaults', () => {
  const props = { bars: [1,null,2,3,4], ma: [1,2,null,3,4], surge: false, label: 'fixture chart' }
  const chart = render(<MiniBars {...props} connectNulls={false} />)
  expect(chart.container.querySelectorAll('rect')).toHaveLength(4)
  expect(chart.container.querySelectorAll('polyline')).toHaveLength(2)
  chart.rerender(<MiniBars {...props} />)
  expect(chart.container.querySelectorAll('polyline')).toHaveLength(1)
})

it('labels stored zero-baseline flags without claiming a newly created market', () => {
  const zeroBaseline = { ...item, metrics: { ...item.metrics, flag: 'new', reason: '비교값 0은 원자료 미검증 상태입니다.' } }
  state.query = ready({ ...data, rows: [zeroBaseline] }); const list = show()
  expect(screen.getByText('비교값 0')).toBeTruthy()
  expect(screen.queryByText('신규')).toBeNull()
  list.unmount(); show('/follow/trade/8542')
  expect(screen.getByText('비교값 0')).toBeTruthy()
  expect(screen.getByText('비교값 0은 원자료 미검증 상태입니다.')).toBeTruthy()
  expect(screen.queryByText('신규')).toBeNull()
})

it('keeps rolling three-month growth, z and absolute-change contribution in detail', () => {
  state.query = ready({ ...data, rows: [{ ...item, metrics: { ...item.metrics, qoq: .123, z: 1.25, contribution: .456, delta_usd: -2000000 } }] })
  show('/follow/trade/8542')
  const detail = screen.getByRole('region', { name: '공개 품목 상세' })
  expect(within(detail).getByText('직전 3개월 합 대비')).toBeTruthy()
  expect(within(detail).getByText('+12.3%')).toBeTruthy()
  expect(within(detail).getByText('평소 대비 z')).toBeTruthy()
  expect(within(detail).getByText('1.25')).toBeTruthy()
  expect(within(detail).getByText('절대 증감 기여도')).toBeTruthy()
  expect(within(detail).getByText('45.6%')).toBeTruthy()
  expect(within(detail).getByText('−$2.0M')).toBeTruthy()
  expect(within(detail).getByText(/달력상 분기 비교가 아닙니다/).textContent).toContain('순증가 비율이 아닙니다')
})
