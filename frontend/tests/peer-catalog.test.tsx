import { afterEach, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import PeerCatalogPage from '@/components/peers/PeerCatalogPage'
import raw from '@/data/peer-catalog.json'
import { parsePeerCatalog, selectPeerCompanies } from '@/lib/peerCatalog'
import { locate } from '@/components/layout/navConfig'

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

it('restores URL filters, opens evidence, and preserves search when changing groups and going back', async () => {
  mount('/discover/peers?view=research&group=power_transformer&q=103590')
  expect(await screen.findByRole('link', { name: '일진전기' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: '대한전선' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /사업 근거/ }))
  expect(await screen.findAllByRole('link', { name: /dart.fss.or.kr/ })).not.toHaveLength(0)
  fireEvent.click(screen.getAllByRole('button', { name: /전력 케이블/ })[0])
  await waitFor(() => expect(screen.getByLabelText('현재 URL').textContent).toContain('group=power_cable'))
  expect(screen.getByLabelText('기업명·종목코드·제품 검색').getAttribute('value')).toBe('103590')
  fireEvent.click(screen.getByRole('button', { name: '테스트 뒤로' }))
  await waitFor(() => expect(screen.getByLabelText('현재 URL').textContent).toContain('group=power_transformer'))
})

it('does not substitute all companies for an invalid group and resets explicitly', async () => {
  mount('/discover/peers?view=research&group=does-not-exist&q=103590')
  expect(await screen.findByRole('heading', { name: '그룹을 찾을 수 없습니다' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: '일진전기' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '필터 초기화' }))
  expect(await screen.findByRole('link', { name: '일진전기' })).toBeTruthy()
  expect(screen.getByLabelText('현재 URL').textContent).toBe('/discover/peers?view=research')
})
