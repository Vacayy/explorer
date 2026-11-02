import prices from '@/data/peer-prices.json'
import catalog from '@/data/peer-catalog.json'
import api from '@/api/client'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PeerCatalogPage from '@/components/peers/PeerCatalogPage'

vi.mock('@/components/charts/MultiLineChart', () => ({ default: ({ data }: { data: unknown[] }) => <output aria-label="차트 데이터">{JSON.stringify(data)}</output> }))
vi.spyOn(api, 'get').mockImplementation(async () => ({ data: {
  catalog, prices, origin: 'collector', publishedAt: prices.collectedAt, baselineOn: '2026-11-01',
  lastAttempt: { at: prices.collectedAt, status: 'error', asOf: null, error: 'test collection failure' },
  priceAgeDays: 2, snapshotAgeHours: 1, signalStatus: 'held', signalHoldReason: '기업행사 조정 검증 미완료',
} }))
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0 })
function Location() { return <output aria-label="URL">{useLocation().search}</output> }
function mount(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><PeerCatalogPage /><Location /></MemoryRouter></QueryClientProvider>)
}

it('shows audited numbers, changes period and keeps price chart/table on the same window', async () => {
  mount('/discover/peers?group=test_socket&days=20&stock=425420')
  expect(await screen.findByText('+62.8%p')).toBeTruthy()
  expect(JSON.parse(screen.getByLabelText('차트 데이터').textContent!)).toHaveLength(21)
  fireEvent.click(screen.getByText('5거래일'))
  await waitFor(() => expect(screen.getByText('+41.7%p')).toBeTruthy())
  expect(JSON.parse(screen.getByLabelText('차트 데이터').textContent!)).toHaveLength(6)
  expect(screen.getByLabelText('URL').textContent).toContain('days=5')
  expect(screen.getByText(/자동 신호 발행 안 함/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '사업 근거 보기' }))
  expect(await screen.findByRole('link', { name: '티에프이' })).toBeTruthy()
  expect(screen.getByLabelText('URL').textContent).toContain('view=research')
})

it('finds relative strength candidates, filters weakness and opens the selected group and stock', async () => {
  mount('/discover/peers?overview=candidates&days=20')
  expect(await screen.findByRole('link', { name: '티에프이' })).toBeTruthy()
  fireEvent.click(screen.getByText('상대 약세', { selector: 'button' }))
  await waitFor(() => expect(screen.queryByRole('link', { name: '티에프이' })).toBeNull())
  fireEvent.click(screen.getByText('상대 강세', { selector: 'button' }))
  expect(await screen.findByRole('link', { name: '티에프이' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '패키지 테스트 소켓·핀', exact: true }))
  await waitFor(() => expect(screen.getByLabelText('URL').textContent).toContain('group=test_socket'))
  expect(screen.getByLabelText('URL').textContent).toContain('stock=425420')
})

it('does not replace invalid group/stock selections with a different comparison', async () => {
  mount('/discover/peers?group=test_socket&stock=DOES_NOT_EXIST')
  expect(await screen.findByText(/선택한 종목이 이 그룹에 없습니다/)).toBeTruthy()
  const chart = JSON.parse(screen.getByLabelText('차트 데이터').textContent!)
  expect(chart.every((point: Record<string, unknown>) => !('stock_DOES_NOT_EXIST' in point))).toBe(true)
  expect(Object.keys(chart[0]).filter(key => key.startsWith('stock_')).length).toBeGreaterThan(1)
})

it('shows collection failure while retaining the published comparison', async () => {
  mount('/discover/peers?group=test_socket')
  expect(await screen.findByText(/실패 — 마지막 정상본 표시/)).toBeTruthy()
  expect(screen.getByText(/자동 신호 보류/)).toBeTruthy()
  expect(screen.getByLabelText('차트 데이터')).toBeTruthy()
})

it('opens a complete power preset without selections and drills into the automatic parent benchmark', async () => {
  mount('/discover/peers')
  expect(await screen.findByText('조사된 구성 종목 6개 · 전체 비교')).toBeTruthy()
  expect(screen.queryByLabelText('비교 기준 그룹')).toBeNull()
  const chart = JSON.parse(screen.getByLabelText('차트 데이터').textContent!)
  expect(Object.keys(chart[0]).filter(key => key.startsWith('stock_'))).toHaveLength(6)
  expect(screen.getByRole('region', { name: '세부 사업군 비교' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '전력 변압기', exact: true }))
  await waitFor(() => expect(screen.getByText(/비교 기준: 전력 인프라 · 자동 기준 · 상위 산업군/)).toBeTruthy())
  expect(screen.getByLabelText('URL').textContent).toContain('group=power_transformer')
})

it('resets manual benchmark and highlighted stock when selecting a new preset', async () => {
  mount('/discover/peers?group=test_socket&benchmark=battery_cell&stock=425420&days=60&settings=1')
  expect(await screen.findByLabelText('비교 기준 그룹')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /^전력 인프라/ }))
  await waitFor(() => expect(screen.getByLabelText('URL').textContent).not.toContain('benchmark='))
  expect(screen.getByLabelText('URL').textContent).not.toContain('stock=')
  expect(screen.getByLabelText('URL').textContent).toContain('days=60')
  expect(screen.queryByLabelText('비교 기준 그룹')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '사업 근거 보기', exact: true }))
  expect(await screen.findByRole('link', { name: '일진전기' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: '티에프이' })).toBeNull()
})

it('explains an unavailable automatic benchmark even when the selected subgroup has complete prices', async () => {
  mount('/discover/peers?group=battery_cell&days=60')
  expect(await screen.findByText(/비교 기준 배터리 밸류체인은 가격 관측/)).toBeTruthy()
  expect(screen.getByText(/에코프로비엠 · 2026-09-03/)).toBeTruthy()
  expect(screen.queryByText(/회색 점선: 비교 기준/)).toBeNull()
  const chart = JSON.parse(screen.getByLabelText('차트 데이터').textContent!)
  expect(chart[0].group).toBe(100)
  expect(chart.every((point: Record<string, unknown>) => point.baseline === undefined)).toBe(true)
})

it('groups repeated quality warnings without losing date-specific sources', async () => {
  mount('/discover/peers?group=nuclear_value_chain&days=20')
  expect(await screen.findByText(/우진엔텍 · 2026-10-02 외 7일/)).toBeTruthy()
  const trigger = screen.getByRole('button', { name: '날짜별 근거 8건' })
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  fireEvent.click(trigger)
  expect(screen.getByRole('link', { name: '2026-10-02 근거 (새 창)' }).getAttribute('href')).toMatch(/^https:/)
  expect(screen.getByRole('link', { name: '2026-10-15 근거 (새 창)' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '수집 상세' }))
  expect(screen.getByText(/관측 시작 2026-11-01/)).toBeTruthy()
  expect(screen.getByText(/실패 — 마지막 정상본 표시/)).toBeTruthy()
})
