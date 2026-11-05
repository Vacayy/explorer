import prices from '@/data/peer-prices.json'
import catalog from '@/data/peer-catalog.json'
import api from '@/api/client'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import SectorBoard from '@/components/industry/SectorBoard'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { SectorGroup, SectorPeers } from '@/types'
import { SECTOR_PEERS_FIXTURE } from './fixtures/sectorPeers'

// 산업 › 산업·섹터 '섹터 → Peer 그룹' 블록 — 대응표는 서버(GET /api/spine/sector-map/peers, D-301 6)
vi.mock('@/components/charts/MultiLineChart', () => ({ default: () => <output aria-label="차트" /> }))

const sector = (name: string, market_cap: number): SectorGroup => ({ name, market_cap, stocks: 10, rs_long: 50, rs_short: 50, chg_5d: 1, trail: [] })
const MAP = { as_of: '2026-11-04', groups: [sector('반도체·전자부품', 9e14), sector('건설·부동산', 5e13), sector('바이오·헬스케어', 2e14), sector('철강·금속', 4e13)] }
const AUTO: SectorPeers = {
  ...SECTOR_PEERS_FIXTURE,
  sectors: SECTOR_PEERS_FIXTURE.sectors.map(e => e.sector !== '철강·금속' ? e : {
    ...e, links: [{ group_id: 'instrumentation_fittings', group_name: '계장용 피팅·밸브', scope: 'product', source: 'auto', partial: false, members: 2, classified: 2, in_sector: 2, share: 1 }],
  }),
}
const RUNTIME = { catalog, prices, origin: 'collector', publishedAt: prices.collectedAt, baselineOn: '2026-11-01', lastAttempt: null,
  priceAgeDays: 1, snapshotAgeHours: 1, signalStatus: 'held', signalHoldReason: '검증 미완료' }

let peersResponse: () => Promise<unknown> = async () => ({ data: AUTO })
vi.spyOn(api, 'get').mockImplementation((async (url: string) => {
  if (url.includes('/sector-map/peers')) return peersResponse()
  if (url.includes('/sector-map')) return { data: MAP }
  return { data: RUNTIME }
}) as never)

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.forEach(c => c.clear()); clients.length = 0; peersResponse = async () => ({ data: AUTO }) })

function mount(url = '/map?group=건설·부동산') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); clients.push(client)
  render(<QueryClientProvider client={client}><TooltipProvider><MemoryRouter initialEntries={[url]}><SectorBoard /></MemoryRouter></TooltipProvider></QueryClientProvider>)
}
const row = (name: string) => document.querySelector(`[data-sector-peer="${name}"]`) as HTMLElement

it('ideal: linked, partial, auto-suggested and unlinked sectors from the server map', async () => {
  mount()
  expect(await screen.findByText('4개 중 3개 연결 · 부분 1')).toBeTruthy()
  expect(within(row('반도체·전자부품')).getByRole('link', { name: /반도체 밸류체인/ }).getAttribute('href')).toBe('/discover/peers?group=semiconductor_value_chain')
  expect(within(row('건설·부동산')).getByText('부분')).toBeTruthy()
  expect(within(row('건설·부동산')).getAllByRole('link')).toHaveLength(2)
  expect(within(row('철강·금속')).getByText('자동')).toBeTruthy()
  expect(within(row('철강·금속')).getByRole('link', { name: /계장용 피팅/ })).toBeTruthy()
  expect(within(row('바이오·헬스케어')).getByText('연결된 Peer 그룹 없음')).toBeTruthy()
  expect(within(row('바이오·헬스케어')).queryByText('자동')).toBeNull()
})

it('loading then error: the map block and the Peer block show the server map failure with retry', async () => {
  peersResponse = async () => { throw new Error('boom') }
  mount()
  expect((await screen.findAllByText('섹터 → Peer 대응표를 불러오지 못했습니다')).length).toBe(2)
  expect(screen.queryByText(/개 중 .*개 연결/)).toBeNull()
})

it('loading: skeleton rows until the server map arrives', async () => {
  peersResponse = () => new Promise(() => {})
  mount()
  await screen.findAllByText('건설·부동산')
  expect(row('건설·부동산')).toBeNull()
  expect(screen.queryByText('연결된 Peer 그룹 없음')).toBeNull()
})
