import prices from '@/data/peer-prices.json'
import catalog from '@/data/peer-catalog.json'
import api from '@/api/client'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import PeerCatalogPage from '@/components/peers/PeerCatalogPage'
import raw from '@/data/peer-catalog.json'
import { parsePeerCatalog, selectPeerCompanies } from '@/lib/peerCatalog'
import { locate } from '@/components/layout/navConfig'

vi.spyOn(api, 'get').mockImplementation(async () => ({ data: {
  catalog, prices, origin: 'collector', publishedAt: prices.collectedAt, baselineOn: '2026-11-01',
  lastAttempt: { at: prices.collectedAt, status: 'error', asOf: null, error: 'test collection failure' },
  priceAgeDays: 2, snapshotAgeHours: 1, signalStatus: 'held', signalHoldReason: '기업행사 조정 검증 미완료',
} }))
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0 })

it('validates the shipped evidence graph, rejects missing references and unsafe URLs', () => {
  const catalog = parsePeerCatalog(raw)
  expect(catalog.companies.length).toBeGreaterThanOrEqual(53)
  expect(catalog.companies.every(company => company.sources.length > 0)).toBe(true)
  const missing = structuredClone(raw); missing.companies[0].groupIds.push('absent')
  expect(() => parsePeerCatalog(missing)).toThrow('없는 그룹')
  const unsafe = structuredClone(raw); unsafe.companies[0].sources[0].url = 'javascript:alert(1)'
  expect(() => parsePeerCatalog(unsafe)).toThrow()
  const duplicate = structuredClone(raw); duplicate.companies.push(duplicate.companies[0])
  expect(() => parsePeerCatalog(duplicate)).toThrow('중복 종목')
})

it('intersects product search with group membership without double counting', () => {
  const catalog = parsePeerCatalog(raw)
  expect(selectPeerCompanies(catalog, 'power_transformer', '103590').map(c => c.name)).toEqual(['일진전기'])
  expect(selectPeerCompanies(catalog, 'power_cable', '103590')).toHaveLength(1)
  expect(selectPeerCompanies(catalog, '', '103590')).toHaveLength(1)
  expect(selectPeerCompanies(catalog, 'test_socket', '103590')).toHaveLength(0)
  expect(selectPeerCompanies(catalog, '', 'LIG넥스원').map(c => c.code)).toEqual(['079550'])
  expect(locate('/discover/peers')).toEqual({ section: 'explore', tab: 'peers' })
})

function Location() {
  const location = useLocation(); const navigate = useNavigate()
  return <><output aria-label="현재 URL">{location.pathname + location.search}</output><button onClick={() => navigate(-1)}>테스트 뒤로</button></>
}
function mount(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><PeerCatalogPage /><Location /></MemoryRouter></QueryClientProvider>)
}

it('research view lists evidence sources with hosts and lets going back restore the previous group', async () => {
  mount('/discover/peers?view=research&group=power_transformer&stock=103590')
  expect(await screen.findAllByRole('link', { name: /dart\.fss\.or\.kr/ })).not.toHaveLength(0)
  const card = screen.getByRole('button', { name: /일진전기/, expanded: true }).closest('li')!
  fireEvent.click(within(card).getByRole('button', { name: '전력 케이블' }))
  await waitFor(() => expect(screen.getByLabelText('현재 URL').textContent).toContain('group=power_cable'))
  fireEvent.click(screen.getByRole('button', { name: '테스트 뒤로' }))
  await waitFor(() => expect(screen.getByLabelText('현재 URL').textContent).toContain('group=power_transformer'))
})
