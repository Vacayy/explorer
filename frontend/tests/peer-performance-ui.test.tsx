import prices from '@/data/peer-prices.json'
import catalog from '@/data/peer-catalog.json'
import api from '@/api/client'
import { SECTOR_PEERS_FIXTURE } from './fixtures/sectorPeers'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SectorPeersTab from '@/components/industry/SectorPeersTab'
import { peerRedirectTarget } from '@/components/industry/IndustryRedirects'
import { peerParent } from '@/lib/peerPresets'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { SectorPeerList } from '@/types'

// 섹터 화면 › Peer 그룹 탭 — 옛 탐색 › Peer 그룹 본체(ia-redesign §4.12 계약 · §4.35, D-327 안 A).
// 왼쪽 하위 그룹 목록 | 오른쪽 그룹 본문(위치 · 요약 띠 · 선택한 종목 · 성과 비교 | 사업 근거)
beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})
vi.mock('@/components/charts/MultiLineChart', () => ({ default: ({ data, lines }: { data: unknown[]; lines: { key: string; lineWidth?: number }[] }) => <output aria-label="차트 데이터" data-lines={JSON.stringify(lines.map(l => [l.key, l.lineWidth]))}>{JSON.stringify(data)}</output> }))
const parsed = parsePeerCatalog(catalog)
const runtime = (lastAttempt: unknown = { at: prices.collectedAt, status: 'error', asOf: null, error: 'test collection failure' }) => ({ data: {
  catalog, prices, origin: 'collector', publishedAt: prices.collectedAt, baselineOn: '2026-11-01',
  lastAttempt, priceAgeDays: 2, snapshotAgeHours: 1, signalStatus: 'held', signalHoldReason: '기업행사 조정 검증 미완료',
} })
// 서버 하위 그룹 목록 대역 — 카탈로그 전 그룹(상위 그룹 위계 그대로), 중앙값은 순서만 맞춘다
const LIST: SectorPeerList = { sector: '전력·에너지', catalog_as_of: '2026-11-04', prices_as_of: prices.asOf, groups: parsed.groups.map((g, i) => ({
  id: g.id, name: g.name, scope: g.scope, parent: peerParent(parsed, g.id) ?? null, partial: false, auto: false,
  members: parsed.companies.filter(c => c.groupIds.includes(g.id)).length, med_20d: null, med_60d: 100 - i,
})) }
const byUrl = (url: string) => url.includes('/sector-map/peers') ? { data: SECTOR_PEERS_FIXTURE } : url.includes('/api/spine/industry/') ? { data: LIST } : runtime()
const get = vi.spyOn(api, 'get').mockImplementation(async (url: string) => byUrl(url) as never)
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; get.mockImplementation(async (url: string) => byUrl(url) as never) })
function Location() { return <output aria-label="URL">{useLocation().search}</output> }
function mount(search: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); clients.push(client)
  render(<QueryClientProvider client={client}><TooltipProvider><MemoryRouter initialEntries={[`/industry/x${search}`]}>
    <Routes><Route path="/industry/:sector" element={<><SectorPeersTab sector="전력·에너지" /><Location /></>} /></Routes>
  </MemoryRouter></TooltipProvider></QueryClientProvider>)
}
const url = () => screen.getByLabelText('URL').textContent!

it('shows the shared frame: location path, 4-cell summary, list and the top performer as the default stock', async () => {
  mount('?tab=peers&group=test_socket')
  const path = await screen.findByRole('navigation', { name: '그룹 위치' })
  expect(path.textContent).toBe('전력·에너지›반도체 밸류체인›패키지 테스트 소켓·핀')
  const summary = screen.getByRole('region', { name: '그룹 요약' })
  expect(within(summary).getByText('4사')).toBeTruthy()
  expect(within(summary).getByText(/원문 확인/)).toBeTruthy()
  const band = screen.getByRole('region', { name: '선택한 종목' })
  const table = screen.getByRole('table', { name: '구성 종목 성과표' })
  const first = within(table).getAllByRole('row')[1]
  expect(first.textContent).toMatch(/^1/)
  expect(band.textContent).toContain(within(first).getAllByRole('button')[0].textContent!)
  expect(within(table).getByText('그룹 평균')).toBeTruthy()
  expect(screen.getByLabelText('하위 그룹 목록')).toBeTruthy()
})

it('keeps chart and table on the same window when the period changes, defaulting to 60 days', async () => {
  mount('?tab=peers&group=test_socket&stock=425420')
  await screen.findByRole('table', { name: '구성 종목 성과표' })
  expect(JSON.parse(screen.getByLabelText('차트 데이터').textContent!)).toHaveLength(61)
  fireEvent.click(screen.getByRole('radio', { name: '5일' }))
  await waitFor(() => expect(JSON.parse(screen.getByLabelText('차트 데이터').textContent!)).toHaveLength(6))
  expect(url()).toContain('days=5')
  const lines = JSON.parse(screen.getByLabelText('차트 데이터').getAttribute('data-lines')!) as [string, number][]
  expect(lines.find(([key]) => key === 'stock_425420')?.[1]).toBe(2)
  expect(lines.filter(([key]) => key.startsWith('stock_') && key !== 'stock_425420').every(([, width]) => width === 1)).toBe(true)
})

it('switches views keeping group, stock and days; the research view expands only the selected card', async () => {
  mount('?tab=peers&group=test_socket&stock=425420&days=20')
  fireEvent.click(await screen.findByRole('button', { name: '사업 근거 보기 ›' }))
  await waitFor(() => expect(url()).toContain('view=research'))
  for (const part of ['group=test_socket', 'stock=425420', 'days=20', 'tab=peers']) expect(url()).toContain(part)
  expect(await screen.findByRole('region', { name: '이 그룹을 묶은 기준' })).toBeTruthy()
  const cards = within(screen.getByRole('region', { name: '구성 종목' })).getAllByRole('button', { expanded: true })
  expect(cards).toHaveLength(1)
  expect(cards[0].textContent).toContain('티에프이')
  fireEvent.click(screen.getByRole('button', { name: '성과 비교로 보기 ›' }))
  await waitFor(() => expect(url()).toContain('view=performance'))
  expect(url()).toContain('stock=425420')
})

it('changing the group in the list clears the stock but keeps view, period and search', async () => {
  mount('?tab=peers&group=test_socket&stock=425420&days=20&view=research&q=변압기')
  const list = await screen.findByLabelText('하위 그룹 목록')
  fireEvent.click(within(list).getByRole('button', { name: /^전력 변압기/ }))
  await waitFor(() => expect(url()).toContain('group=power_transformer'))
  expect(url()).not.toContain('stock=')
  for (const part of ['days=20', 'view=research', 'tab=peers']) expect(url()).toContain(part)
  expect(decodeURIComponent(url())).toContain('q=변압기')
})

it('search narrows only the list and says so when nothing matches', async () => {
  mount('?tab=peers&group=test_socket&q=존재하지않는제품')
  expect(await screen.findByText(/들어간 그룹이 없습니다/)).toBeTruthy()
  expect(screen.getByRole('table', { name: '구성 종목 성과표' })).toBeTruthy()
})

it('partial prices: keeps the row with "-", drops it from chart and average and states the count', async () => {
  mount('?tab=peers&group=battery_value_chain&days=60')
  expect(await screen.findByText(/가격 없는 종목 1개/)).toBeTruthy()
  const table = screen.getByRole('table', { name: '구성 종목 성과표' })
  const row = within(table).getByRole('button', { name: '에코프로비엠' }).closest('tr')!
  expect(row.textContent).toContain('-')
  const chart = JSON.parse(screen.getByLabelText('차트 데이터').textContent!)
  expect(chart.every((point: Record<string, unknown>) => point.stock_247540 === undefined)).toBe(true)
  expect(within(table).getByText('3/4사')).toBeTruthy()
})

it('does not substitute an invalid stock or a group outside the sector with a different comparison', async () => {
  mount('?tab=peers&group=test_socket&stock=DOES_NOT_EXIST')
  expect(await screen.findByText(/선택한 종목이 이 그룹에 없습니다/)).toBeTruthy()
  cleanup()
  mount('?tab=peers&group=does-not-exist')
  expect(await screen.findByText('이 그룹은 이 섹터에 걸려 있지 않습니다.')).toBeTruthy()
  expect(screen.queryByRole('table', { name: '구성 종목 성과표' })).toBeNull()
  expect(screen.getByLabelText('하위 그룹 목록')).toBeTruthy()
})

it('without ?group opens the top group of the list', async () => {
  mount('?tab=peers')
  const path = await screen.findByRole('navigation', { name: '그룹 위치' })
  expect(path.textContent).toContain(LIST.groups[0].name)
})

it('shows collection failure as a state line while retaining the published comparison', async () => {
  mount('?tab=peers&group=test_socket')
  expect(await screen.findByText(/마지막 수집에 실패해/)).toBeTruthy()
  expect(screen.getByLabelText('차트 데이터')).toBeTruthy()
})

it('keeps the list and offers retry in the body when the Peer runtime fails', async () => {
  get.mockImplementation(async (u: string) => { if (u.includes('/api/peers/runtime')) throw new Error('boom'); return byUrl(u) as never })
  mount('?tab=peers&group=test_socket')
  expect(await screen.findByRole('button', { name: '다시 시도' })).toBeTruthy()
  expect(await screen.findByLabelText('하위 그룹 목록')).toBeTruthy()
})

it('old Peer addresses go to the sector screen Peer tab; ungrouped groups to the map search', () => {
  const c = parsed
  const s = SECTOR_PEERS_FIXTURE.sectors
  const sector = (to: string) => decodeURIComponent(to)
  expect(sector(peerRedirectTarget('?view=research&group=package_substrate&stock=007810', c, s)))
    .toBe('/industry/반도체·전자부품?tab=peers&group=package_substrate&view=research&stock=007810')
  // /analyze/compare?stocks= — 그 종목이 가장 많이 든 그룹과 첫 종목
  expect(sector(peerRedirectTarget('?stocks=103590,298040', c, s))).toBe('/industry/전력·에너지?tab=peers&group=power_transformer&stock=103590')
  // 옛 단계 링크(layer=businesses&industry=X)는 X를 그룹으로
  expect(sector(peerRedirectTarget('?layer=businesses&industry=bank_financial_holding&days=20', c, s))).toBe('/industry/금융?tab=peers&group=bank_financial_holding&days=20')
  expect(peerRedirectTarget('', c, s)).toBe('/industry')
  expect(peerRedirectTarget('?group=nope', c, s)).toBe('/industry')
  const outside = c.groups.find(g => !s.some(e => e.links.some(l => l.group_id === g.id)) && !peerParent(c, g.id))
  if (outside) expect(sector(peerRedirectTarget(`?group=${outside.id}`, c, s))).toBe(`/industry?q=${outside.name}`)
})
