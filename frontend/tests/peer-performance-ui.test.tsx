import prices from '@/data/peer-prices.json'
import catalog from '@/data/peer-catalog.json'
import api from '@/api/client'
import { SECTOR_PEERS_FIXTURE } from './fixtures/sectorPeers'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PeerCatalogPage from '@/components/peers/PeerCatalogPage'

// 탐색 › Peer 그룹 — 성과 비교와 사업 근거가 같은 틀(경로·요약 띠·그룹 찾기·선택한 종목)을 쓴다 (ia-redesign §4.12·§4.28)
vi.mock('@/components/charts/MultiLineChart', () => ({ default: ({ data, lines }: { data: unknown[]; lines: { key: string; lineWidth?: number }[] }) => <output aria-label="차트 데이터" data-lines={JSON.stringify(lines.map(l => [l.key, l.lineWidth]))}>{JSON.stringify(data)}</output> }))
const runtime = (lastAttempt: unknown = { at: prices.collectedAt, status: 'error', asOf: null, error: 'test collection failure' }) => ({ data: {
  catalog, prices, origin: 'collector', publishedAt: prices.collectedAt, baselineOn: '2026-11-01',
  lastAttempt, priceAgeDays: 2, snapshotAgeHours: 1, signalStatus: 'held', signalHoldReason: '기업행사 조정 검증 미완료',
} })
const byUrl = (url: string) => url.includes('/sector-map/peers') ? { data: SECTOR_PEERS_FIXTURE } : runtime()
const get = vi.spyOn(api, 'get').mockImplementation(async (url: string) => byUrl(url) as never)
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; get.mockImplementation(async (url: string) => byUrl(url) as never) })
function Location() { return <output aria-label="URL">{useLocation().search}</output> }
function mount(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><PeerCatalogPage /><Location /></MemoryRouter></QueryClientProvider>)
}
const url = () => screen.getByLabelText('URL').textContent!

it('shows the shared frame: breadcrumb, 4-cell summary, finder and the top performer as the default stock', async () => {
  mount('/discover/peers?group=test_socket')
  const crumbs = await screen.findByRole('navigation', { name: '그룹 경로' })
  expect(crumbs.textContent).toBe('업종 전체반도체 밸류체인패키지 테스트 소켓·핀')
  const summary = screen.getByRole('region', { name: '그룹 요약' })
  expect(within(summary).getByText('4사')).toBeTruthy()
  expect(within(summary).getByText(/원문 확인/)).toBeTruthy()
  const band = screen.getByRole('region', { name: '선택한 종목' })
  const table = screen.getByRole('table', { name: '구성 종목 성과표' })
  const first = within(table).getAllByRole('row')[1]
  expect(first.textContent).toMatch(/^1/)
  expect(band.textContent).toContain(within(first).getAllByRole('button')[0].textContent!)
  expect(within(table).getByText('그룹 평균')).toBeTruthy()
})

it('keeps chart and table on the same window when the period changes, defaulting to 60 days', async () => {
  mount('/discover/peers?group=test_socket&stock=425420')
  await screen.findByRole('table', { name: '구성 종목 성과표' })
  expect(JSON.parse(screen.getByLabelText('차트 데이터').textContent!)).toHaveLength(61)
  fireEvent.click(screen.getAllByRole('radio', { name: '5일' })[0])
  await waitFor(() => expect(JSON.parse(screen.getByLabelText('차트 데이터').textContent!)).toHaveLength(6))
  expect(url()).toContain('days=5')
  // 선택한 종목만 굵게
  const lines = JSON.parse(screen.getByLabelText('차트 데이터').getAttribute('data-lines')!) as [string, number][]
  expect(lines.find(([key]) => key === 'stock_425420')?.[1]).toBe(3)
  expect(lines.filter(([key]) => key.startsWith('stock_') && key !== 'stock_425420').every(([, width]) => width === 1)).toBe(true)
})

it('switches views keeping group, stock and days; the research view expands only the selected card', async () => {
  mount('/discover/peers?group=test_socket&stock=425420&days=20')
  fireEvent.click(await screen.findByRole('button', { name: '사업 근거 보기 ›' }))
  await waitFor(() => expect(url()).toContain('view=research'))
  for (const part of ['group=test_socket', 'stock=425420', 'days=20']) expect(url()).toContain(part)
  expect(await screen.findByRole('region', { name: '이 그룹을 묶은 기준' })).toBeTruthy()
  const cards = within(screen.getByRole('region', { name: '구성 종목' })).getAllByRole('button', { expanded: true })
  expect(cards).toHaveLength(1)
  expect(cards[0].textContent).toContain('티에프이')
  fireEvent.click(screen.getByRole('button', { name: '성과 비교로 보기 ›' }))
  await waitFor(() => expect(url()).toContain('view=performance'))
  expect(url()).toContain('stock=425420')
})

it('changing the group in the finder clears the stock but keeps view, period and search', async () => {
  mount('/discover/peers?group=test_socket&stock=425420&days=20&view=research&q=변압기')
  const finder = await screen.findByRole('complementary', { name: '그룹 찾기' })
  fireEvent.click(within(finder).getByRole('button', { name: /^전력 변압기/ }))
  await waitFor(() => expect(url()).toContain('group=power_transformer'))
  expect(url()).not.toContain('stock=')
  for (const part of ['days=20', 'view=research']) expect(url()).toContain(part)
  expect(decodeURIComponent(url())).toContain('q=변압기')
})

it('search narrows only the finder and says so when nothing matches', async () => {
  mount('/discover/peers?group=test_socket&q=존재하지않는제품')
  const finder = await screen.findByRole('complementary', { name: '그룹 찾기' })
  expect(within(finder).getByText(/들어간 그룹이 없습니다/)).toBeTruthy()
  expect(screen.getByRole('table', { name: '구성 종목 성과표' })).toBeTruthy()
})

it('partial prices: keeps the row with "-", drops it from chart and average and states the count', async () => {
  mount('/discover/peers?group=battery_value_chain&days=60')
  expect(await screen.findByText(/가격 없는 종목 1개/)).toBeTruthy()
  const table = screen.getByRole('table', { name: '구성 종목 성과표' })
  const row = within(table).getByRole('button', { name: '에코프로비엠' }).closest('tr')!
  expect(row.textContent).toContain('-')
  const chart = JSON.parse(screen.getByLabelText('차트 데이터').textContent!)
  expect(chart.every((point: Record<string, unknown>) => point.stock_247540 === undefined)).toBe(true)
  expect(within(table).getByText('3/4사')).toBeTruthy()
})

it('does not substitute an invalid stock or group with a different comparison', async () => {
  mount('/discover/peers?group=test_socket&stock=DOES_NOT_EXIST')
  expect(await screen.findByText(/선택한 종목이 이 그룹에 없습니다/)).toBeTruthy()
  cleanup()
  mount('/discover/peers?group=does-not-exist')
  expect(await screen.findByText('이 업종에는 아직 Peer 그룹이 없습니다.')).toBeTruthy()
  expect(screen.queryByRole('table', { name: '구성 종목 성과표' })).toBeNull()
  expect(screen.getByRole('complementary', { name: '그룹 찾기' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '업종 전체로 돌아가기 ›' }))
  expect(await screen.findByRole('table', { name: '업종 간 비교 성과표' })).toBeTruthy()
})

it('shows collection failure as a state line while retaining the published comparison', async () => {
  mount('/discover/peers?group=test_socket')
  expect(await screen.findByText(/마지막 수집에 실패해/)).toBeTruthy()
  expect(screen.getByLabelText('차트 데이터')).toBeTruthy()
})

it('lands on 업종 전체 and drills into an industry with its business groups', async () => {
  mount('/discover/peers?days=5')
  const table = await screen.findByRole('table', { name: '업종 간 비교 성과표' })
  fireEvent.click(within(table).getByRole('button', { name: '전력 인프라' }))
  await waitFor(() => expect(url()).toContain('group=power_infrastructure'))
  const businesses = await screen.findByRole('region', { name: '세부 사업군' })
  fireEvent.click(within(businesses).getByRole('button', { name: '전력 변압기' }))
  await waitFor(() => expect(url()).toContain('group=power_transformer'))
  expect(url()).toContain('days=5')
  fireEvent.click(within(screen.getByRole('navigation', { name: '그룹 경로' })).getByRole('button', { name: '전력 인프라' }))
  await waitFor(() => expect(url()).toContain('group=power_infrastructure'))
})

it('opens the group holding compared stocks from /analyze/compare?stocks=', async () => {
  mount('/discover/peers?stocks=103590,298040')
  await waitFor(() => expect(url()).toContain('group=power_transformer'))
  expect(url()).toContain('stock=103590')
  expect(url()).not.toContain('stocks=')
})

it('keeps the frame and offers retry when the runtime fails', async () => {
  get.mockImplementation(async () => { throw new Error('boom') })
  mount('/discover/peers?group=test_socket')
  expect(await screen.findByRole('button', { name: '다시 시도' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Peer 그룹' })).toBeTruthy()
})
