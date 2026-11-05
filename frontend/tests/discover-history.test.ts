import { expect, it } from 'vitest'
import { filterRuns, groupRunsByDay, lastSearch, runFilterCounts, runOutcome, runScope, runTitle, runWhen } from '@/lib/discoverHistory'
import type { AnalysisRun } from '@/components/analysis/types'

const labels = { trading_range: '박스권(고점·저점 수평)', resistance_break: '전고점 돌파', close_above_sma: '200일 이평 위' }
const run = (over: Partial<AnalysisRun>): AnalysisRun => ({
  id: 'r', question: '국내 전체 시장에서 다음 조건을 모두 만족하는 종목을 찾아줘.\n- 박스권', status: 'partial', phase: 'done', created_at: '2026-10-14T05:51:33Z', updated_at: '',
  spec: { mode: 'catalog', market: 'all', min_market_cap: 0, strategy_conditions: [{ strategy_id: 'trading_range', params: {}, within_days: 1 }, { strategy_id: 'resistance_break', params: {}, within_days: 1 }] },
  result: { as_of: '2026-10-13', counts: { universe: 3000, evaluated: 2608, matched: 34, excluded: 392 }, condition_funnel: { evaluated: 2608, conditions: [{ strategy_id: 'trading_range', passed: 383, sole_blocker: 220 }, { strategy_id: 'resistance_break', passed: 254, sole_blocker: 350 }] } },
  pending: null, error: null, cost_usd: 0, active_seconds: 0, steps: 0, artifacts: [], snapshot: null, cost_uncertain: false, ...over,
} as unknown as AnalysisRun)

it('titles catalog searches by condition names and sentence searches by their text', () => {
  expect(runTitle(run({}), labels)).toBe('박스권(고점·저점 수평) · 전고점 돌파')
  expect(runTitle(run({ spec: null, question: "다음 조건을 찾아줘.\n- '전력 병목' 수혜" }), labels)).toBe("다음 조건을 찾아줘. '전력 병목' 수혜")
})

it('classifies outcomes and counts filters (pending runs only in 전체)', () => {
  const runs = [run({}), run({ result: { ...run({}).result!, counts: { universe: 1, evaluated: 1, matched: 0, excluded: 0 } } }), run({ status: 'failed', result: null }), run({ status: 'running', result: null })]
  expect(runs.map(runOutcome)).toEqual(['matched', 'empty', 'error', 'pending'])
  expect(runFilterCounts(runs)).toEqual({ all: 4, matched: 1, empty: 1, error: 1 })
  expect(filterRuns(runs, 'error', '', labels)).toHaveLength(1)
  expect(filterRuns(runs, 'all', '전고점', labels)).toHaveLength(4)
  expect(filterRuns(runs, 'all', '이평', labels)).toHaveLength(0)
})

it('describes scope, groups by KST day and uses relative time only within 6 days', () => {
  expect(runScope(run({}))).toBe('국내 전체')
  expect(runScope(run({ spec: { ...run({}).spec!, min_market_cap: 30_000_000_000, universe_codes: ['050090', '018000'] } }))).toBe('국내 전체 · 시총 300억+ · 지정 2종목')
  const groups = groupRunsByDay([run({ created_at: '2026-10-30T23:46:21Z' }), run({ created_at: '2026-10-14T05:51:33Z' }), run({ created_at: '2026-10-14T05:50:00Z' })])
  expect(groups.map(g => [g.day, g.items.length])).toEqual([['10월 31일', 1], ['10월 14일', 2]])
  const now = new Date('2026-11-04T12:00:00Z').getTime()
  expect(runWhen('2026-10-14T05:51:33Z', now)).toBe('10/14 14:51')
  expect(runWhen('2026-11-03T12:00:00Z', now)).not.toMatch(/\//)
})

it('last search card picks the latest run with a result and names the tightest condition', () => {
  const card = lastSearch([run({ id: 'x', status: 'failed', result: null }), run({ id: 'y' })], labels)!
  expect(card).toMatchObject({ id: 'y', matched: 34, evaluated: 2608, bottleneck: { label: '전고점 돌파', passed: 254 } })
  expect(lastSearch([], labels)).toBeNull()
})
