import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PeerCatalogPage from '@/components/peers/PeerCatalogPage'

vi.mock('@/components/charts/MultiLineChart', () => ({ default: ({ data }: { data: unknown[] }) => <output aria-label="차트 데이터">{JSON.stringify(data)}</output> }))
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
  expect(chart.every((point: { stock?: number }) => point.stock === undefined)).toBe(true)
})
