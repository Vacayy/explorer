import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import type { CorporateAction } from '../src/types'

/* 홈 › 한국 시장 ④ 기업활동 칸 — 6개씩 페이지(ui/pagination), 보기(전체 | 내 그룹)를 바꾸면 첫 페이지로(D-325) */
const act = (i: number): CorporateAction => ({
  id: i, rcp_no: String(i), corp_name: `기업${i}`, stock_code: null, market: 'Y', action_type: '유상증자', report_nm: `공시${i}`,
  rcept_dt: '20261104', market_cap: null, summary: null, description: i === 0 ? '주주배정 · 1차 발행가 1,000원' : null, dart_url: '#', is_correction: false,
  my_group: i < 2 ? '관심' : null,
})
vi.mock('@/hooks/useActions', async (orig) => ({
  ...(await orig<typeof import('../src/hooks/useActions')>()),
  useActions: () => ({ isLoading: false, isError: false, refetch: () => {}, data: { items: Array.from({ length: 15 }, (_, i) => act(i)), total: 15, as_of: '2026-11-06 01:00:00', counts: { original: 15, correction: 0 } } }),
}))
vi.mock('@/components/actions/RightsProTable', () => ({ default: () => null }))
const { ActionsList } = await import('../src/components/actions/ActionsPage')

afterEach(() => cleanup())
const renderAt = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter><ActionsList variant="block" /></MemoryRouter></TooltipProvider></QueryClientProvider>)
const rows = () => screen.queryAllByText(/^기업\d+$/).map(e => e.textContent)

it('pages the home block 6 rows at a time', () => {
  renderAt()
  expect(rows()).toEqual(['기업0', '기업1', '기업2', '기업3', '기업4', '기업5'])
  expect(screen.getByText('1–6 / 15')).toBeTruthy()
  expect(screen.getByText('주주배정 · 1차 발행가 1,000원')).toBeTruthy()          // 한 줄 설명(D-306)
  fireEvent.click(screen.getByRole('link', { name: '3페이지' }))
  expect(rows()).toEqual(['기업12', '기업13', '기업14'])
  fireEvent.click(screen.getByRole('radio', { name: '내 그룹' }))                 // 보기를 바꾸면 첫 페이지
  expect(rows()).toEqual(['기업0', '기업1'])
})
