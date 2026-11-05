import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import type { CorporateAction } from '../src/types'

/* 홈 › 한국 시장 기업활동 블록 — 데스크톱 10·모바일 6행 + 더 보기, 필터를 바꾸면 다시 접힌다(D-303) */
const act = (i: number): CorporateAction => ({
  id: i, rcp_no: String(i), corp_name: `기업${i}`, stock_code: null, market: 'Y', action_type: '유상증자', report_nm: `공시${i}`,
  rcept_dt: '20261104', market_cap: null, summary: null, description: i === 0 ? '주주배정 · 1차 발행가 1,000원' : null, dart_url: '#', is_correction: false, my_group: null,
})
const mobile = { value: false }
vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => mobile.value }))
vi.mock('@/hooks/useActions', async (orig) => ({
  ...(await orig<typeof import('../src/hooks/useActions')>()),
  useActions: () => ({ isLoading: false, isError: false, refetch: () => {}, data: { items: Array.from({ length: 15 }, (_, i) => act(i)), total: 15, as_of: null, counts: { original: 15, correction: 0 } } }),
}))
vi.mock('@/components/actions/RightsProTable', () => ({ default: () => null }))
const { ActionsList } = await import('../src/components/actions/ActionsPage')

afterEach(() => { cleanup(); mobile.value = false })
const renderAt = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter><ActionsList variant="block" /></MemoryRouter></TooltipProvider></QueryClientProvider>)
const rows = () => screen.queryAllByText(/^기업\d+$/).length

it('bounds the home block to 10 rows on desktop and expands on 더 보기', () => {
  renderAt()
  expect(rows()).toBe(10)
  fireEvent.click(screen.getByRole('button', { name: /5건 더 보기/ }))
  expect(rows()).toBe(15)
  expect(screen.queryByRole('button', { name: /더 보기/ })).toBeNull()
  fireEvent.click(screen.getByText('합병'))                     // 필터를 바꾸면 다시 접힌다
  expect(rows()).toBe(10)
})

it('shows 6 rows on mobile', () => {
  mobile.value = true
  renderAt()
  expect(rows()).toBe(6)
})

it('shows the one-line description under the report title', () => {
  renderAt()
  const desc = screen.getAllByText('주주배정 · 1차 발행가 1,000원')
  expect(desc.length).toBeGreaterThan(0)
  expect(desc[0].getAttribute('data-action-desc')).not.toBeNull()
})
