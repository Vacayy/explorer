import api from '@/api/client'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SectorPage from '@/components/industry/SectorPage'
import IndustryMapPage from '@/components/industry/IndustryMapPage'
import { benchmarkTip, zoneMove, zoneOf } from '@/components/industry/sectorParts'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { IndustryMap, IndustrySectorDetail } from '@/types'

// 산업 › 섹터 지도 · 섹터 화면 (ia-redesign §4.35, D-327) — 대표지수 표시 규칙·탭·개요 빈 상태·종목 페이지
beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})

const ETF = { kind: 'etf' as const, ticker: '091160', name: 'KODEX 반도체', tracks: 'KRX 반도체', note: null }
const COMPUTED = { kind: 'computed' as const, ticker: null, name: null, tracks: null, note: '통신 업종 ETF가 없습니다.' }
const trail = [{ weeks_ago: 1, rs_long: 90, rs_short: 30 }, { weeks_ago: 3, rs_long: 80, rs_short: 70 }, { weeks_ago: 2, rs_long: 85, rs_short: 60 }]
const stocks = Array.from({ length: 45 }, (_, i) => ({ stock_code: String(100000 + i), corp_name: `종목${i + 1}`, market_cap: 1e12 - i, weight: 1, chg_1d: 1, ret_1m: -2, rs_long: 50, rs_short: 50 }))
const DETAIL: IndustrySectorDetail = {
  as_of: '2026-11-05', name: '반도체·전자부품', benchmark: ETF, last: 93110, last_date: '2026-11-05', chg_1d: -11.26, ret_1m: -38.36, ret_3m: -16.8,
  rs_long: 100, rs_short: 12, chg_5d: -14.6, trail, market_cap: 2.3e15, stocks: 45,
  series: Array.from({ length: 300 }, (_, i) => ({ d: new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10), v: 100 + i, k: 50 + i / 2 })),
  top_weights: stocks.slice(0, 8), constituents: stocks,
  narratives: [{ id: 1, topic: '메모리', title: '메모리 부족이 길어집니다', core_question: null, docs: 25, updated_at: '2026-11-03' }],
  overview: null, docs: [{ id: 9, type: 'blog', title: '반도체, 과거 사이클', published_at: '2026-11-05T00:00:00+00:00' }],
  peer_groups: 27,
  data_links: [{ kind: 'trade', label: '수출입', title: '메모리반도체', value: 37.6e9, value_kind: 'usd', change: 302.2, sub: '9월 · 전년 대비', count: 71, href: '/follow/trade?grp=반도체', filtered: false, verdict: null }],
  feed_industry: '반도체', entity_id: 3949,
}
const MAP: IndustryMap = { as_of: '2026-11-05', kospi: [100, 101, 102], peers_available: true, outside_groups: [], sectors: [
  { name: '반도체·전자부품', benchmark: ETF, last: 93110, last_date: '2026-11-05', chg_1d: -1, ret_1m: -38.4, ret_3m: -17, rs_long: 100, rs_short: 12, chg_5d: -14.6, trail, market_cap: 2.3e15, stocks: 375, peer_groups: 27, series: [10, 11, 9] },
  { name: '통신', benchmark: COMPUTED, last: 120.5, last_date: '2026-11-05', chg_1d: 0.4, ret_1m: -4.6, ret_3m: -1, rs_long: 71, rs_short: 82, chg_5d: 7.9, trail: [], market_cap: 3.8e13, stocks: 14, peer_groups: 0, series: [10, 10.5, 11] },
] }
const get = vi.spyOn(api, 'get').mockImplementation(async (url: string) => (url.includes('/industry/map') ? { data: MAP } : url.includes('/follows') ? { data: [] } : url.endsWith('/peers') ? { data: { sector: 'x', catalog_as_of: '', prices_as_of: '', groups: [] } } : url.includes('/api/peers/runtime') ? Promise.reject(new Error('no runtime')) : { data: DETAIL }) as never)
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.forEach(c => c.clear()); clients.length = 0 })
function Location() { const l = useLocation(); return <output aria-label="URL">{l.pathname + l.search}</output> }
function mount(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); clients.push(client)
  render(<QueryClientProvider client={client}><TooltipProvider><MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/industry" element={<IndustryMapPage />} /><Route path="/industry/:sector" element={<SectorPage />} /></Routes><Location />
  </MemoryRouter></TooltipProvider></QueryClientProvider>)
}

it('zones: 가로 단기 · 세로 장기, move shows the oldest trail point → now', () => {
  expect(zoneOf(80, 70)).toBe('주도')
  expect(zoneOf(80, 20)).toBe('숨 고르기')
  expect(zoneOf(20, 80)).toBe('반등 시도')
  expect(zoneOf(20, 20)).toBe('소외')
  expect(zoneMove({ rs_long: 100, rs_short: 12, trail })).toBe('주도 → 숨 고르기')
  expect(zoneMove({ rs_long: 100, rs_short: 12, trail: [] })).toBe('숨 고르기')
})

it('benchmark tooltip names what the ETF tracks; computed sectors say so instead of inventing a name', () => {
  expect(benchmarkTip(ETF)).toContain('KODEX 반도체(091160) — KRX 반도체 지수를 따라가는 ETF')
  expect(benchmarkTip(COMPUTED)).toContain('Explorer가 이 섹터 종목을 시가총액으로 가중해 계산한 지수')
})

it('sector head shows the ETF name and code, RS badges, zone move and tab counts; overview waits for narratives', async () => {
  mount('/industry/반도체·전자부품')
  expect(await screen.findByText('93,110')).toBeTruthy()
  expect(screen.getAllByText('KODEX 반도체').length).toBeGreaterThan(0)
  expect(screen.getAllByText('091160').length).toBeGreaterThan(0)
  expect(screen.getByText('주도 → 숨 고르기')).toBeTruthy()
  expect(screen.getByRole('tab', { name: /Peer 그룹\s*27/ })).toBeTruthy()
  expect(screen.getByText('개괄은 내러티브가 바뀌면 만들어집니다.')).toBeTruthy()
  expect(screen.getByText('메모리 부족이 길어집니다')).toBeTruthy()
  expect(screen.getByRole('link', { name: /반도체, 과거 사이클/ }).getAttribute('href')).toBe('/doc/9')
  // 개요의 Peer 그룹 칸 = Peer 탭과 같은 컴포넌트, 그 아래 전체 폭 데이터 줄
  expect(await screen.findAllByText('이 업종엔 아직 Peer 그룹이 없습니다.')).not.toHaveLength(0)
  expect(screen.getByRole('region', { name: '이 산업의 데이터' })).toBeTruthy()
})

it('stocks tab pages constituents 20 at a time through the URL', async () => {
  mount('/industry/반도체·전자부품?tab=stocks')
  const table = await screen.findByRole('table')
  expect(within(table).getAllByRole('row')).toHaveLength(21)
  fireEvent.click(screen.getByRole('link', { name: '3페이지' }))
  await waitFor(() => expect(screen.getByLabelText('URL').textContent).toContain('page=3'))
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(6)
})

it('map: computed sectors are labelled honestly on cards and every card opens its sector screen', async () => {
  mount('/industry?v=table')
  const cards = await screen.findAllByRole('link', { name: /섹터 화면$/ })
  expect(cards.map(a => decodeURIComponent(a.getAttribute('href')!))).toEqual(['/industry/반도체·전자부품', '/industry/통신'])
  expect(screen.getAllByLabelText('섹터 순위').length).toBeGreaterThan(0)
  expect(get).toHaveBeenCalledWith('/api/spine/industry/map', expect.anything())
})
