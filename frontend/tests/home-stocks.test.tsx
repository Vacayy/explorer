import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import { earningsBadge, featured, signalDetail, sortRows, splitRows } from '../src/lib/myStocks'
import type { SeasonOverview, StockGroupDetail, StockGroupMember, TrackerView } from '../src/types'

/* ── 순수 규칙 ── */
const sig = (strategy_id: string, value: number | null = null, reference: number | null = null, label = strategy_id) =>
  ({ rule_id: 1, strategy_id, label, value, reference, signal_date: '2026-11-04' })
const member = (stock_code: string, over: Partial<StockGroupMember> = {}): StockGroupMember => ({
  id: 1, group_id: 1, stock_code, name: stock_code, market: 'KOSDAQ', bought_at: null, conviction: null, target_price: null, thesis: null,
  created_at: '', tracked: 0, close: 1000, change_pct: 0, market_cap: null, price_date: '2026-11-04', rule_count: 1, signals: [], unavailable: 0, ...over,
})
const MEMBERS = [
  member('A', { change_pct: -1 }),
  member('B', { tracked: 1, change_pct: -1.09 }),
  member('C', { change_pct: -9, signals: [sig('volume_increase', 40)] }),
  member('ROP', { market: 'us', name: 'Roper Technologies', close: 479.54, change_pct: 2.77, signals: [sig('high_20d', 484.17, 470.01, '20일 신고가 갱신')] }),
  member('D', { tracked: 1, change_pct: -9.09 }),
  member('E', { change_pct: -12 }),
  member('SITM', { market: 'us', name: 'SiTime', change_pct: -8.4, signals: [sig('volume_increase', 118)] }),
]

it('orders rows: tracked first, then rows with a signal, then by size of the move', () => {
  expect(sortRows(MEMBERS).map(m => m.stock_code)).toEqual(['D', 'B', 'C', 'SITM', 'ROP', 'E', 'A'])
  const split = splitRows(MEMBERS, 3)
  expect([split.tracked.map(m => m.stock_code), split.untracked.map(m => m.stock_code), split.hidden]).toEqual([['D', 'B'], ['C', 'SITM', 'ROP'], 2])
})

it('orders featured stocks: new-high signal first, then by volume increase', () => {
  expect(featured(MEMBERS).map(m => m.stock_code)).toEqual(['ROP', 'SITM', 'C'])
})

it('writes the evidence line per signal kind in the stock currency', () => {
  expect(signalDetail(sig('volume_increase', 118))).toBe('거래량 전일 대비 +118.0%')
  expect(signalDetail(sig('high_20d', 484.17, 470.01), 'us')).toBe('고가 $484.17 — 직전 고점 $470.01 돌파')
  expect(signalDetail(sig('high_20d', 18010, 17500), 'KOSDAQ')).toBe('고가 18,010원 — 직전 고점 17,500원 돌파')
})

it('builds the US earnings badge from the season data', () => {
  const season = { upcoming: [{ ticker: 'SITM', event_date: '2026-11-05', transcript_id: null }],
    reported: [{ ticker: 'ROP', event_date: '2026-10-22', d1: 11.9, transcript_id: 7 }] } as unknown as SeasonOverview
  expect(earningsBadge('SITM', season, '2026-11-04')).toEqual({ label: '실적 D-1', to: null })
  expect(earningsBadge('ROP', season, '2026-11-04')).toEqual({ label: '실적 10/22 · +11.9%p', to: '/follow/transcripts?t=7' })
  expect(earningsBadge('STRL', season, '2026-11-04')).toBeNull()
})

/* ── 화면 ── */
const mutate = { setTracked: vi.fn(), remove: vi.fn(), add: vi.fn() }
let detail: StockGroupDetail
const card = (code: string, conditions: TrackerView['conditions'] = []): TrackerView => ({
  code, name: code, market: 'kr', price: 1000, change_pct: 0, as_of: '2026-11-04', source: 'close', last_close_date: '2026-11-04', chart: { series: [] },
  technicals: { signals: [] }, flows: null, issues: { disclosures: [], docs_7d: 0, docs: [], target_prices: [] }, conditions,
})
const CARDS: Record<string, TrackerView> = {
  B: card('B', [{ id: 9, stock_code: 'B', role: 'check', kind: 'manual', label: '3분기 실적 확인', done: 1, status: 'met', newly_met: true }]),
  D: card('D'),
}

vi.mock('@/hooks/useGroups', () => ({
  useDefaultWatchGroup: () => ({ isPending: false, isError: false, data: detail, refetch: () => {} }),
  useSetTracked: () => ({ mutateAsync: mutate.setTracked, isPending: false }),
  useRemoveMember: () => ({ mutateAsync: mutate.remove, isPending: false }),
  useAddMember: () => ({ mutateAsync: mutate.add, isPending: false }),
}))
vi.mock('@/hooks/useTracker', () => ({
  useTrackers: (codes: string[]) => codes.map(c => ({ data: CARDS[c] })),
  useTracker: (code: string) => ({ isPending: false, isError: false, data: CARDS[code], refetch: () => {} }),
}))
vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))
vi.mock('@/hooks/useTranscripts', () => ({ useSeason: () => ({ data: undefined }) }))
vi.mock('@/hooks/usePortfolio', () => ({ usePortfolio: () => ({ isPending: false, data: { holdings: [{ code: 'A' }] } }) }))
vi.mock('@/hooks/useStockSearch', () => ({ useStockSearch: () => ({ isPending: false, data: { companies: [], us: [] } }) }))
vi.mock('@/components/home/HomeSection', () => ({ HomeSection: ({ widget }: { widget: string }) => <div data-section={widget} /> }))
vi.mock('@/components/widgets/tracker', () => ({ TrackerBody: () => <div>tracker</div> }))
const { default: HomeStocksPage } = await import('../src/components/home/HomeStocksPage')

beforeEach(() => {
  detail = { id: 1, name: '관심 종목', kind: 'watch', note: '', created_at: '', updated_at: '', members: MEMBERS, rules: { default: [], members: {} },
    last_as_of: '2026-11-04', latest_trade_date: '2026-11-04', evaluation_pending: false, today_signals: 3 }
  mutate.setTracked.mockReset().mockResolvedValue({ group_id: 1, stock_code: 'ROP', tracked: true, tracked_codes: ['B', 'D', 'ROP'] })
  mutate.remove.mockReset().mockResolvedValue(detail)
})
afterEach(() => cleanup())
const renderAt = (path = '/home/stocks') => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}><HomeStocksPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)
const codes = () => [...document.querySelectorAll('[data-stocks-list] [data-code]')].map(r => r.getAttribute('data-code'))

it('lists tracked rows first, then six untracked rows and a more button', () => {
  renderAt()
  expect(codes()).toEqual(['D', 'B', 'C', 'SITM', 'ROP', 'E', 'A'])     // 비추적 5개 — 6개 이하라 더 보기 없음
  expect(screen.queryByRole('button', { name: /더 보기/ })).toBeNull()
  detail = { ...detail, members: [...MEMBERS, member('F'), member('G')] }
  cleanup(); renderAt()
  expect(codes().length).toBe(2 + 6)
  fireEvent.click(screen.getByRole('button', { name: '1종목 더 보기 ›' }))
  expect(codes().length).toBe(2 + 7)
})

it('shows the header counts, featured cards and the newly-met alert line that opens the row', () => {
  renderAt()
  expect(screen.getByText(/관심 7종목 · 추적 2\(충족 1\) · 상승 1 · 하락 6/)).toBeTruthy()
  const feat = document.querySelector('[data-stocks-featured=cards]')!
  expect([...feat.querySelectorAll('a[href^="/analyze"], a[href^="/us"]')].map(a => a.textContent).slice(0, 3).map(t => t?.split(/미국|KOSDAQ/)[0])).toEqual(['Roper Technologies', 'SiTime', 'C'])
  fireEvent.click(screen.getByRole('button', { name: /조건 충족\s*B — 3분기 실적 확인/ }))
  expect(document.querySelector('[data-stocks-detail=B]')).toBeTruthy()
})

it('turns tracking on for a US ticker through the toggle API', async () => {
  renderAt()
  const row = document.querySelector('[data-stocks-list] [data-code=ROP]') as HTMLElement
  fireEvent.click(within(row).getByRole('switch', { name: 'Roper Technologies 추적' }))
  await waitFor(() => expect(mutate.setTracked).toHaveBeenCalledWith({ stockCode: 'ROP', tracked: true }))
})

it('removes a plain member at once but asks first when it has a thesis', async () => {
  detail = { ...detail, members: MEMBERS.map(m => m.stock_code === 'E' ? { ...m, thesis: '논지' } : m) }
  renderAt()
  fireEvent.click(screen.getByRole('button', { name: 'A 빼기' }))
  await waitFor(() => expect(mutate.remove).toHaveBeenCalledWith('A'))
  fireEvent.click(screen.getByRole('button', { name: 'E 빼기' }))
  expect(await screen.findByRole('alertdialog')).toBeTruthy()
  expect(mutate.remove).toHaveBeenCalledTimes(1)
})

it('filters to tracked or held rows from the URL view', () => {
  renderAt('/home/stocks?view=tracked')
  expect(codes()).toEqual(['D', 'B'])
  cleanup(); renderAt('/home/stocks?view=held')
  expect(codes()).toEqual(['A'])
  expect(document.querySelector('[data-section="portfolio.today"]')).toBeTruthy()
})

it('shows only the add action when there are no watch members', () => {
  detail = { ...detail, members: [] }
  renderAt()
  expect(document.querySelector('[data-stocks-state=empty]')).toBeTruthy()
  expect(document.querySelector('[data-stocks-list]')).toBeNull()
  expect(screen.getAllByRole('button', { name: /종목 추가/ }).length).toBeGreaterThan(0)
})
