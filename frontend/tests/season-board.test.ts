import { describe, expect, it } from 'vitest'
import { accelLine, calendarBars, calendarSummary, coreTiles, defaultCalendarDay, momentumFor, reactionLists, sectorDots, sectorRows, seasonNeighbors, weekOf } from '@/lib/seasonBoard'
import type { CallMomentum, CallMomentumCandidate, SeasonItem, SeasonSectorRow } from '@/types'

const item = (o: Partial<SeasonItem> & { ticker: string }): SeasonItem => ({
  name: null, sector: 's1', sector_name: 'S1', event_date: '2026-10-20', fiscal: 'FY2026 Q3', transcript_id: null, reaction: null,
  core: [], eps_surprise: null, headline: null, interpretation: null, confirmed: true, ...o,
})
const cand = (o: Partial<CallMomentumCandidate> & { ticker: string }): CallMomentumCandidate => ({
  name: null, event_date: '2026-10-28', score: 5, first_candidate_at: null, drivers: [], guidance: [], tone: null, prev_tone: null, sources: [], qa_focus: [], ...o,
})
const momentum = (o: Partial<CallMomentum> = {}): CallMomentum => ({
  season: { key: '2026Q3', label: '', start: '2026-10-01', reported: 0 }, candidates: [], continuing: [], history: [],
  coverage: { universe: 0, with_releases: 0, with_transcripts: 0, extracted_docs: 0, failed_docs: 0, comparable: 0 }, sec_configured: true, ...o,
})

describe('발표 캘린더', () => {
  const cal = [
    { date: '2026-10-29', total: 3, core: 1, confirmed: 3, tickers: ['A', 'B', 'C'] },
    { date: '2026-11-03', total: 2, core: 2, confirmed: 1, tickers: ['D', 'E'] },
    { date: '2026-11-05', total: 1, core: 0, confirmed: 0, tickers: ['F'] },
  ]
  it('거래일마다 막대 하나, 주말은 빼고 빈 날은 0', () => {
    const bars = calendarBars(cal)
    expect(bars.map(b => b.date)).toEqual(['2026-10-29', '2026-10-30', '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05'])
    expect(bars[1].total).toBe(0)
    expect(bars[3].estimated).toBe(1)
  })
  it('주말 발표는 막대로 남긴다', () => {
    expect(calendarBars([{ date: '2026-10-31', total: 1, core: 0, confirmed: 1, tickers: ['X'] }]).map(b => b.date)).toEqual(['2026-10-31'])
  })
  it('이번 주(월~일) 남은 발표·가장 많은 날·마지막 날', () => {
    expect(weekOf('2026-11-04')).toEqual({ start: '2026-11-02', end: '2026-11-08' })
    const s = calendarSummary(cal, '2026-11-04')
    expect(s.weekLeft).toBe(1)
    expect(s.weekLeftCore).toBe(0)
    expect(s.peak?.date).toBe('2026-10-29')
    expect(s.last).toBe('2026-11-05')
    expect(s.total).toBe(6)
  })
  it('기본 선택은 오늘 또는 다음 발표일', () => {
    expect(defaultCalendarDay(cal, '2026-11-03')).toBe('2026-11-03')
    expect(defaultCalendarDay(cal, '2026-11-04')).toBe('2026-11-05')
    expect(defaultCalendarDay(cal, '2026-12-01')).toBe('2026-11-05')
    expect(defaultCalendarDay([], '2026-12-01')).toBeNull()
  })
})

describe('새 모멘텀 묶음', () => {
  it('이번 시즌은 새로 붙은(점수순)과 이어지는으로 나눈다', () => {
    const m = momentumFor(momentum({ candidates: [cand({ ticker: 'A', score: 5 }), cand({ ticker: 'B', score: 9 })], continuing: [cand({ ticker: 'C' })] }), '2026Q3')
    expect(m.fresh.map(c => c.ticker)).toEqual(['B', 'A'])
    expect(m.byTicker.get('C')?.kind).toBe('continuing')
    expect(m.byTicker.size).toBe(3)
  })
  it('지난 시즌은 기록에서, 없으면 비운다', () => {
    const src = momentum({ history: [{ key: '2026Q2', label: '', start: '', candidates: [cand({ ticker: 'Z' })] }] })
    expect(momentumFor(src, '2026Q2').fresh.map(c => c.ticker)).toEqual(['Z'])
    expect(momentumFor(src, '2025Q1').byTicker.size).toBe(0)
    expect(momentumFor(undefined, '2026Q3').fresh).toEqual([])
  })
  it('가속 근거: 수치 → 원문 → 올린 가이던스', () => {
    expect(accelLine(cand({ ticker: 'A', accel: { on: true, basis: 'numeric', quarter: '2026-09', g_now: 61.2, g_prev: 24.1, gap: 37.1, beat: null, guidance_raised: true } })))
      .toEqual({ kind: 'numeric', text: '매출 성장 +24.1%→+61.2% · 가이던스 상향' })
    expect(accelLine(cand({ ticker: 'B', accel: { on: true, basis: 'quote', quote: 'Exceeded' } })).kind).toBe('quote')
    expect(accelLine(cand({ ticker: 'C', accel: { on: false, basis: 'none' }, guidance: [{ metric: 'sales', direction: 'raised', quote: '', source: 'release' }, { metric: 'sales', direction: 'raised', quote: '', source: 'release' }] })))
      .toEqual({ kind: 'guidance', text: '가이던스 상향 · sales' })
  })
})

describe('섹터 줄', () => {
  const reported = [item({ ticker: 'A', d1: 30 }), item({ ticker: 'B', d1: -4 }), item({ ticker: 'C', sector: 's2', d1: -10 }), item({ ticker: 'D', d1: null })]
  const row = (key: string, verdict: string | null, dc = false): SeasonSectorRow => ({ key, name: key, etf: 'XLI', verdict, one_line: null, n_reported: 1, n_reactions: 0, tickers: [], dc_chain: dc })
  it('점 띠는 ±25에서 자르고 실제 값은 남긴다', () => {
    const dots = sectorDots(reported, 's1')
    expect(dots.map(d => d.ticker)).toEqual(['B', 'A'])
    expect(dots[1]).toMatchObject({ v: 30, x: 1 })
  })
  it('정렬: 판정순은 서버 순서, 반응 나쁜 순은 중앙값 오름차순, 모멘텀 많은 순', () => {
    const sectors = [row('s1', '엇갈림'), row('s2', '실망 우세'), row('s3', null)]
    const m = momentumFor(momentum({ candidates: [cand({ ticker: 'C' })] }), '2026Q3')
    expect(sectorRows(sectors, reported, m, 'verdict').main.map(r => r.key)).toEqual(['s1', 's2'])
    expect(sectorRows(sectors, reported, m, 'worst').main.map(r => r.key)).toEqual(['s2', 's1'])
    const byM = sectorRows(sectors, reported, m, 'momentum')
    expect(byM.main.map(r => r.key)).toEqual(['s2', 's1'])
    expect(byM.main[0].momentum).toBe(1)
    expect(byM.rest.map(r => r.key)).toEqual(['s3'])
  })
})

describe('반응 보드 탭', () => {
  it('좋았다 · 숫자와 반대로 · 뒤집혔다', () => {
    const l = reactionLists([
      item({ ticker: 'A', d1: 5 }), item({ ticker: 'B', d1: 12, eps_surprise: -3 }), item({ ticker: 'C', d1: -8, eps_surprise: 4, follow: '반전', latest: 2 }),
      item({ ticker: 'D', d1: -1, follow: '되돌림', latest: 0 }),
    ])
    expect(l.good.map(i => i.ticker)).toEqual(['B', 'A'])
    expect(l.opposite.map(i => i.ticker)).toEqual(['B', 'C'])
    expect(l.reversed.map(i => i.ticker)).toEqual(['C', 'D'])
  })
})

describe('핵심 종목 진행판', () => {
  it('곧 발표 → 발표 완료(높은 순) → 반응 대기 → 일정 미정', () => {
    const core = { criteria: {} as never, tickers: ['A', 'B', 'C', 'D', 'E', 'F'].map(t => ({ ticker: t, name: null, reasons: ['cap' as const] })) }
    const reported = [item({ ticker: 'A', d1: 2 }), item({ ticker: 'B', d1: 9 }), item({ ticker: 'C', d1: null })]
    const cal = [{ date: '2026-11-03', total: 1, core: 1, confirmed: 0, tickers: ['D'] }, { date: '2026-11-06', total: 1, core: 1, confirmed: 0, tickers: ['E'] }]
    const m = momentumFor(momentum({ candidates: [cand({ ticker: 'B' })] }), '2026Q3')
    const tiles = coreTiles(core, reported, cal, '2026-11-04', m)
    expect(tiles.map(t => `${t.ticker}:${t.state}`)).toEqual(['E:upcoming', 'B:reported', 'A:reported', 'C:reported', 'D:waiting', 'F:none'])
    expect(tiles[1].momentum).toBe(true)
  })
})

describe('시즌 선택기', () => {
  it('이전·다음', () => {
    expect(seasonNeighbors(['a', 'b', 'c'], 'b')).toEqual({ prev: 'a', next: 'c' })
    expect(seasonNeighbors(['a', 'b'], 'a')).toEqual({ prev: null, next: 'b' })
    expect(seasonNeighbors(['a'], 'z')).toEqual({ prev: null, next: null })
  })
})
