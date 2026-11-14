import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import { daysBetween, groupByDate, seasonPhase } from '../src/lib/seasonPhase'
import { tradeIsLagging } from '../src/lib/trade'
import type { SeasonItem, SeasonOverview, SeasonWindow } from '../src/types'

const W: SeasonWindow[] = [
  { key: '2026Q2', label: '2026년 2분기 실적 시즌', first: '2026-07-09', last: '2026-09-30', events: 137, confirmed: 137 },
  { key: '2026Q3', label: '2026년 3분기 실적 시즌', first: '2026-10-07', last: '2026-12-23', events: 141, confirmed: 90 },
  { key: '2026Q4', label: '2026년 4분기 실적 시즌', first: '2027-01-06', last: '2027-02-24', events: 78, confirmed: 0 },
]

it('is in season from the first to the last report day of a season (no 막바지 variant)', () => {
  for (const d of ['2026-10-07', '2026-11-04', '2026-12-23']) expect(seasonPhase(d, W)).toMatchObject({ state: 'in', current: { key: '2026Q3' } })
})

it('is between seasons from the day after the last report to the day before the next first report', () => {
  expect(seasonPhase('2026-12-24', W)).toMatchObject({ state: 'between', next: { key: '2026Q4' }, last: { key: '2026Q3' }, daysToNext: 13 })
  expect(seasonPhase('2027-01-05', W)).toMatchObject({ state: 'between', next: { key: '2026Q4' }, last: { key: '2026Q3' }, daysToNext: 1 })
  expect(seasonPhase('2026-10-01', W)).toMatchObject({ state: 'between', next: { key: '2026Q3' }, last: { key: '2026Q2' }, daysToNext: 6 })
  expect(seasonPhase('2027-03-01', W)).toMatchObject({ state: 'between', next: null, last: { key: '2026Q4' }, daysToNext: null })
})

it('counts days by calendar date across month and year boundaries', () => {
  expect(daysBetween('2026-12-24', '2027-01-06')).toBe(13)
  expect(daysBetween('2026-11-04', '2026-11-04')).toBe(0)
})

it('groups upcoming reports by date and marks a date as estimated if any report is unconfirmed', () => {
  const g = groupByDate([
    { ticker: 'TSM', event_date: '2027-01-14', confirmed: true },
    { ticker: 'APLD', event_date: '2027-01-06', confirmed: false },
    { ticker: 'NFLX', event_date: '2027-01-19', confirmed: true },
    { ticker: 'FAST', event_date: '2027-01-19', confirmed: true },
  ])
  expect(g.map(x => [x.date, x.items.map(i => i.ticker).join('·'), x.estimated])).toEqual([
    ['2027-01-06', 'APLD', true], ['2027-01-14', 'TSM', false], ['2027-01-19', 'NFLX·FAST', false],
  ])
})

it('flags trade stats older than last month as lagging (관세청 mid-month release)', () => {
  expect(tradeIsLagging('2026-09', '2026-11-04')).toBe(true)
  expect(tradeIsLagging('2026-10', '2026-11-20')).toBe(false)
  expect(tradeIsLagging('2026-11', '2027-01-03')).toBe(true)
  expect(tradeIsLagging('2026-12', '2027-01-20')).toBe(false)
})

/* ── 컴포넌트: 시즌 사이 빈 상태 ── */
const item = (ticker: string, event_date: string, confirmed = true): SeasonItem => ({
  ticker, name: ticker, sector: 'semis', sector_name: '반도체', event_date, fiscal: 'FY2026 Q4', transcript_id: null, reaction: null,
  core: [], eps_surprise: null, headline: null, interpretation: null, confirmed,
})
const overview = (key: string, over: Partial<SeasonOverview> = {}): SeasonOverview => ({
  season: { key, label: W.find(w => w.key === key)!.label, start: '2026-10-01', is_current: key === '2026Q3' },
  counts: { followed: 143, reported: 90, beat: 71, beat_down: 31, reversed: 10, up: 39, miss: 8, miss_up: 1, reactions: 46, reactions_final: 20 },
  changes: { reactions: [], themes: [], expectations: [], transcripts: [] }, last_run: null, windows: W,
  sectors: [{ key: 'dc', name: '데이터센터 설비', etf: 'XLI', verdict: '실망 우세', one_line: 'VRT만 올랐습니다.', n_reported: 6, n_reactions: 6, tickers: [{ ticker: 'VRT', d1: 16.6 }], dc_chain: true }],
  top_up: [], miss_up: [], beat_down: [], reversed: [], upcoming: [],
  evals: { hit: 0, underweighted: 0, noise: 0, missed: 0, cases: [] }, core: { criteria: {} as never, tickers: [] }, reported: [],
  ...over,
})

vi.mock('@/hooks/useTranscripts', () => ({
  useSeason: (key?: string | null) => {
    const data = key === '2026Q4'
      ? overview('2026Q4', { upcoming: [item('APLD', '2027-01-06', false), item('TSM', '2027-01-14'), item('NFLX', '2027-01-19'), item('FAST', '2027-01-19')] })
      : overview('2026Q3', { upcoming: [item('APP', '2026-11-04'), item('ARM', '2026-11-05')] })
    return { data, isError: false, error: null, refetch: () => {} }
  },
}))
const { UsSeasonBlock } = await import('../src/components/home/UsSeasonBlock')

afterEach(() => cleanup())
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}><UsSeasonBlock /></MemoryRouter></TooltipProvider></QueryClientProvider>)

it('shows the verdict row, sector rows and upcoming chips in season', () => {
  renderAt('/home/us?today=2026-11-04')
  expect(screen.getByRole('heading', { name: /2026년 3분기 실적 시즌/ })).toBeTruthy()
  expect(screen.getByText('업종보다 강했다')).toBeTruthy()
  expect(screen.getByRole('link', { name: /데이터센터 설비/ }).getAttribute('href')).toBe('/follow/transcripts?view=season&sector=dc')
  expect(screen.getByRole('link', { name: /오늘\s*APP/ })).toBeTruthy()
  expect(document.querySelector('[data-season-state=between]')).toBeNull()
})

it('replaces verdicts and sectors with D-n, last season summary and next reports between seasons', () => {
  renderAt('/home/us?today=2026-12-24')
  expect(screen.getByRole('heading', { name: /다음 실적 시즌까지\s*D-13/ })).toBeTruthy()
  expect(screen.queryByText('이번 시즌 시장이 따진 것')).toBeNull()
  const last = screen.getByRole('region', { name: '지난 시즌 정리' })
  expect(within(last).getByText('90')).toBeTruthy()
  expect(within(last).getByRole('link', { name: /시장이 따진 것 1개 섹터 다시 보기/ }).getAttribute('href')).toBe('/follow/transcripts?view=season&season=2026Q3')
  const next = screen.getByRole('region', { name: '곧 발표 · 팔로우 기업' })
  expect(next.textContent).toContain('1/6')
  expect(next.textContent).toContain('예상일')
  expect(next.textContent).toContain('NFLX · FAST')
  expect(screen.getByRole('region', { name: '그 사이 볼 것' }).textContent).toContain('어젯밤 미국장 브리핑')
})
