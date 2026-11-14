import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'

// 상태 시트(ia-redesign §4.28) 홈 › 매크로 — 블록 단위 실패와 자동 첫 수집 표시
const state = vi.hoisted(() => ({ eraFails: true, allFail: false }))
const ok = <T,>(data: T) => ({ data, isPending: false, isSuccess: true, isError: false, isFetching: false, error: null, refetch: vi.fn() })
const failed = () => ({ data: undefined, isPending: false, isSuccess: false, isError: true, isFetching: false, error: new Error('boom'), refetch: vi.fn() })
const regimes = () => ({ as_of: null, first_date: null, phases: [], corrections: [], recessions: [], trend: [], series: [], current: null,
  params: { bear: 0.2, bull: 0.2, correction: 0.1, near: 0.18, trend_months: 10, version: 'v' } })
const pricing = { days: [], as_of: '2026-11-03', extracted_days: 0, pending: 3, prices: [], claims: [], summary: { new: [], stronger: ['a', 'b'], weaker: [], faded: [] } }

vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))
vi.mock('@/hooks/useRegimes', () => ({
  OVERLAY_KEYS: ['curve'],
  useRegimes: () => state.allFail ? failed() : ok(regimes()),
  useEraState: () => state.eraFails || state.allFail ? failed() : ok(undefined),
  usePricing: () => state.allFail ? failed() : ok(pricing),
  useEraCommentary: () => ok({ body: '## 한 줄 요약\n경고등은 꺼져 있습니다.\n\n## 더\n본문', created_at: null, model: null, stale: true }),
  useGenerateCommentary: () => ({ mutate: vi.fn(), isPending: false }),
  useSetEraCheck: () => ({ mutate: vi.fn() }),
  useAutoCollectRegimes: () => ({ collecting: true, failed: false, error: null, result: undefined }),
  useRegimeOverlay: () => ok({ items: [] }),
  useBrk: () => ok(undefined),
}))
vi.mock('@/hooks/useMacro', () => ({ useMacro: () => ok({ as_of: '2026-11-03', items: [], degraded: ['HYG(신용)'], interpretation: null, signal: null, fred_enabled: true }) }))
vi.mock('@/hooks/useRisk', () => ({ RISK_TILE_KEYS: [], useRiskTiles: () => ok({ items: [], signal: null, empty: true, expected_date: '2026-11-03' }) }))
const { default: HomeMacroPage } = await import('../src/components/home/HomeMacroPage')

afterEach(() => cleanup())
const renderPage = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={['/home/macro']}><HomeMacroPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)

it('keeps pricing and history alive when only the era state fails, and auto-collects an empty history without a button', () => {
  Object.assign(state, { eraFails: true, allFail: false })
  renderPage()
  expect(screen.getByText(/지금 판정\(1~4\)을 불러오지 못했습니다/)).toBeTruthy()
  expect(screen.getByText('판정 불러오기 실패')).toBeTruthy()
  expect(screen.getByText('새로 0')).toBeTruthy()                                   // 5번 칸은 정상
  expect(screen.getByText(/처음 한 번 지수 이력을 받는 중입니다/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: /이력 수집/ })).toBeNull()             // 사용자 화면에 수집 버튼 없음
  expect(screen.queryByText(/소급 추출/)).toBeNull()                                  // 프라이싱 미추출일은 띠의 빈 칸으로만
  expect(screen.getByText(/HYG\(신용\) 원천 지연/)).toBeTruthy()                       // 신호등 degraded
  expect(screen.getByText('새 데이터 있음 · 다시 쓰기 권장')).toBeTruthy()             // 해설은 자동으로 다시 쓰지 않음
  expect(screen.getByText('경고등은 꺼져 있습니다.')).toBeTruthy()
  expect(screen.queryByText('본문')).toBeNull()                                       // 나머지는 '전체 보기'로
})

it('shows one page-level error only when regimes, state and pricing all fail', () => {
  Object.assign(state, { allFail: true })
  renderPage()
  expect(screen.getByRole('alert').textContent).toContain('매크로 화면 데이터를 하나도 불러오지 못했습니다')
  expect(screen.queryByText('지금 시장은')).toBeNull()
})
