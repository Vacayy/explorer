import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import api from '@/api/client'
import type { CompanyWebProfile } from '@/types'

const state = vi.hoisted(() => ({ mobile: false, mutationMounted: vi.fn() }))
vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => state.mobile }))
vi.mock('@tanstack/react-query', async original => {
  const actual = await original<typeof import('@tanstack/react-query')>()
  return { ...actual, useMutation: (...args: Parameters<typeof actual.useMutation>) => { state.mutationMounted(); return actual.useMutation(...args) } }
})
const { CompanyOverviewCard, PublicCompanyOverviewCard } = await import('@/components/company/CompanyOverview')
const clients: QueryClient[] = []
const profile: CompanyWebProfile = {
  id: 1, stock_code: 'AMAT', version: 2, created_at: '2026-11-15T01:00:00Z', model: null, cost_usd: null, reason: null, source_count: 1,
  overview: '저장된 사업 개요', business_lines: [{ name: '반도체 장비', description: '장비 공급', share_pct: null, source_ids: [1] }],
  products_customers: [], competitors: [], drivers: [{ text: '성장 동인 자료', source_ids: [1] }],
  risks: [{ text: '확인할 위험', source_ids: [1] }], recent_events: [], gaps: ['고객별 매출 미확인'],
  sources: [{ id: 1, url: 'https://example.com/ir', title: '출처 제목', publisher: 'IR', published_at: null, kind: 'ir', excerpt: '', fetched: false }],
}
function show(privateView = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client)
  return render(<QueryClientProvider client={client}>{privateView
    ? <CompanyOverviewCard stockCode="AMAT" market="us" fallback={<p>사업 설명 없음</p>} />
    : <PublicCompanyOverviewCard stockCode="AMAT" />}</QueryClientProvider>)
}
beforeEach(() => { state.mobile = false; vi.spyOn(api, 'get').mockResolvedValue({ data: { profile, reuse_hours: 24 } }); vi.spyOn(api, 'post').mockResolvedValue({ data: { profile, reused: true, reuse_hours: 24 } }) })
afterEach(() => { cleanup(); clients.splice(0).forEach(c => c.clear()); vi.restoreAllMocks(); vi.clearAllMocks() })
it('reads the original GET and preserves body, gaps and source uncertainty without mounting research', async () => {
  show()
  expect(await screen.findByText('저장된 사업 개요')).toBeTruthy()
  expect(api.get).toHaveBeenCalledWith('/api/spine/company-profile/AMAT', expect.objectContaining({ params: { market: 'us' } }))
  expect(screen.getByText(/저장 웹 조사 v2 · 작성 11\/15 10:00 KST/)).toBeTruthy()
  expect(screen.getByText('미확인 근거 포함')).toBeTruthy()
  expect(screen.getByText('원문 미확인 · 검색 요약만')).toBeTruthy()
  expect(screen.getByText('고객별 매출 미확인')).toBeTruthy()
  expect(screen.getByRole('link', { name: '출처 제목' }).getAttribute('href')).toBe('https://example.com/ir')
  expect(screen.queryByRole('button', { name: /조사/ })).toBeNull()
  expect(state.mutationMounted).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled()
})
it('shows absent public material without offering generation', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { profile: null, reuse_hours: 24 } }); show()
  expect(await screen.findByText('공개된 기업 개요 자료가 아직 없습니다.')).toBeTruthy()
  expect(state.mutationMounted).not.toHaveBeenCalled()
})
it('retries GET failure without creating a report', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('offline')); show()
  expect(await screen.findByText('기업 개요를 불러오지 못했습니다.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /다시 시도/ }))
  expect(await screen.findByText('저장된 사업 개요')).toBeTruthy()
  expect(api.post).not.toHaveBeenCalled()
})
it('opens the original mobile sheet with risks and sources but no research action', async () => {
  state.mobile = true; show()
  fireEvent.click(await screen.findByRole('button', { name: '개요 전체 · 리스크 · 출처 ›' }))
  const sheet = await screen.findByRole('dialog')
  expect(within(sheet).getByText('확인할 위험')).toBeTruthy()
  expect(within(sheet).getByText('고객별 매출 미확인')).toBeTruthy()
  expect(within(sheet).getByText('원문 미확인 · 검색 요약만')).toBeTruthy()
  expect(within(sheet).queryByRole('button', { name: /조사/ })).toBeNull()
  expect(state.mutationMounted).not.toHaveBeenCalled()
})
it('preserves private explicit research refresh', async () => {
  show(true)
  fireEvent.click(await screen.findByRole('button', { name: '웹으로 다시 조사' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/spine/company-profile/AMAT', { force: true }, expect.objectContaining({ params: { market: 'us' } })))
  expect(state.mutationMounted).toHaveBeenCalled()
})
