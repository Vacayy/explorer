import { expect, it } from 'vitest'
import catalogRaw from '@/data/peer-catalog.json'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { SECTOR_PEERS, groupMedianPath, groupMedianReturn, parseSectorSort, sectorDataLinks, sectorPeerGroups, shortRsTrail, sortSectors } from '@/lib/sectorPeers'
import { creditGroupMedians, defaultCreditPicks, parseCreditRange, sliceByRange } from '@/lib/credit'
import { monthLabel, movingAverage, parseTradeGridSort, rankTradeGrid } from '@/lib/trade'
import type { PeerPriceSnapshot } from '@/types/peer'
import type { CreditRow, TradeFollowRow } from '@/types'

const catalog = parsePeerCatalog(catalogRaw)

it('sector → peer table points at real catalog groups and expands parents to their product groups', () => {
  const ids = new Set(catalog.groups.map(g => g.id))
  for (const [sector, entry] of Object.entries(SECTOR_PEERS)) for (const id of entry.groups) expect(ids.has(id), `${sector} → ${id}`).toBe(true)
  const semis = sectorPeerGroups(catalog, '반도체·전자부품')
  expect(semis.top).toEqual(['semiconductor_value_chain'])
  expect(semis.all.length).toBeGreaterThan(10)
  expect(semis.all[0]).toBe('semiconductor_value_chain')
  expect(new Set(semis.all).size).toBe(semis.all.length)
  const power = sectorPeerGroups(catalog, '전력·에너지')
  expect(power.all).toContain('power_transformer')
  expect(power.all).toContain('nuclear_equipment')
  expect(sectorPeerGroups(catalog, '기계·장비').partial).toBe(true)
  expect(sectorPeerGroups(catalog, '바이오·헬스케어')).toEqual({ top: [], all: [], partial: false, note: null })
})

it('sector data links only where the data covers the sector', () => {
  expect(sectorDataLinks('반도체·전자부품')).toEqual(['trade', 'taiwan', 'valuechain', 'usSeason'])
  expect(sectorDataLinks('금융')).toEqual([])
  expect(sectorDataLinks('조선·해운·운송')).toEqual(['trade'])
})

const snapshot = {
  dates: ['d0', 'd1', 'd2', 'd3', 'd4', 'd5'], asOf: 'd5', qualityIssues: [],
  prices: { '000001': [100, 1, 1, 1, 110, 120], '000002': [100, 1, 1, 1, 90, 80], '000003': [100, 1, 1, 1, 100, 110], '000004': [null, 1, 1, 1, 50, 60] },
} as unknown as PeerPriceSnapshot

it('group median path starts at 100, drops codes without prices and reports coverage', () => {
  const { path, covered } = groupMedianPath(snapshot, ['000001', '000002', '000003', '000004'], 5)
  expect(covered).toBe(3)
  expect(path?.[4]).toBeCloseTo(100)
  expect(path?.[5]).toBeCloseTo(110)
  expect(path?.[0]).toBe(100)
  expect(groupMedianReturn(snapshot, ['000001', '000002'], 5)).toBeCloseTo(0)
  expect(groupMedianPath(snapshot, ['000004'], 5)).toEqual({ path: null, covered: 0 })
})

it('sector sort defaults to market cap and keeps nulls last; RS trail runs oldest → now', () => {
  const rows = [
    { name: 'a', market_cap: 1, rs_long: null, rs_short: 50, chg_5d: 1 },
    { name: 'b', market_cap: 3, rs_long: 10, rs_short: 20, chg_5d: -2 },
    { name: 'c', market_cap: 2, rs_long: 90, rs_short: 80, chg_5d: 3 },
  ]
  expect(parseSectorSort('x')).toBe('cap')
  expect(sortSectors(rows, 'cap').map(r => r.name)).toEqual(['b', 'c', 'a'])
  expect(sortSectors(rows, 'long').map(r => r.name)).toEqual(['c', 'b', 'a'])
  expect(sortSectors(rows, 'chg5').map(r => r.name)).toEqual(['c', 'a', 'b'])
  expect(shortRsTrail({ rs_short: 18, trail: [{ weeks_ago: 1, rs_short: 6 }, { weeks_ago: 3, rs_short: 12 }, { weeks_ago: 2, rs_short: 0 }] }).map(t => t.value)).toEqual([12, 0, 6, 18])
})

const bond = (ticker: string, group: string, spread: number | null, chg: number | null, hy = false) =>
  ({ ticker, name: ticker, group, spread_bp: spread, chg_1m: chg, hy } as CreditRow)

it('credit default picks: 1-month widening first, spread width when the change is still empty', () => {
  expect(defaultCreditPicks([bond('A', 'g', 100, 5), bond('B', 'g', 300, 20), bond('C', 'g', 50, 1)])).toEqual(['B', 'A'])
  expect(defaultCreditPicks([bond('A', 'g', 100, null), bond('B', 'g', 300, null), bond('C', 'g', null, null)])).toEqual(['B', 'A'])
  expect(defaultCreditPicks([bond('A', 'g', 100, 5), bond('B', 'g', 300, null)])).toEqual(['A', 'B'])
})

it('credit group medians keep server order and count bonds without a spread', () => {
  const out = creditGroupMedians([bond('A', 'x', 100, null), bond('B', 'x', 300, null, true), bond('C', 'y', null, null), bond('D', 'x', 200, null)],
    [{ key: 'y', label: 'Y' }, { key: 'x', label: 'X' }])
  expect(out).toEqual([{ key: 'y', label: 'Y', median: null, count: 1, hy: 0 }, { key: 'x', label: 'X', median: 200, count: 3, hy: 1 }])
})

it('credit range slices from the last observation', () => {
  const pts = ['2024-10-01', '2025-08-01', '2025-10-15', '2025-11-03'].map(date => ({ date }))
  expect(parseCreditRange(null)).toBe('1y')
  expect(sliceByRange(pts, '3m').map(p => p.date)).toEqual(['2025-10-15', '2025-11-03'])
  expect(sliceByRange(pts, '1y')).toHaveLength(3)
  expect(sliceByRange(pts, 'all')).toHaveLength(4)
})

const item = (hs: string, value: number | null, flag: TradeFollowRow['flag'] = 'none', nested: string | null = null) =>
  ({ hs_code: hs, item_name: hs, group_label: null, latest_period: '2026-09', latest_export: value, yoy_pct: null, z: null, flag, reason: null, contribution: null, nested_in: nested } as TradeFollowRow)

it('trade grid: top-level items by value; surge-first and mine-first reorder; nested items never shown', () => {
  const rows = [item('a', 10), item('b', 30), item('c', 20, 'surge'), item('d', 99, 'surge', 'b'), item('e', null)]
  expect(rankTradeGrid(rows, 'value').map(r => r.hs_code)).toEqual(['b', 'c', 'a'])
  expect(rankTradeGrid(rows, 'surge').map(r => r.hs_code)).toEqual(['c', 'b', 'a'])
  expect(rankTradeGrid(rows, 'mine', new Set(['a'])).map(r => r.hs_code)).toEqual(['a', 'b', 'c'])
  expect(rankTradeGrid(rows, 'value', new Set(), 2)).toHaveLength(2)
  expect(parseTradeGridSort('group')).toBe('value')
})

it('12-month moving average waits for a full window and breaks on gaps', () => {
  const v = Array.from({ length: 14 }, (_, i) => i + 1) as (number | null)[]
  const ma = movingAverage(v)
  expect(ma.slice(0, 11).every(x => x === null)).toBe(true)
  expect(ma[11]).toBeCloseTo(6.5)
  expect(movingAverage([...v.slice(0, 12), null, 1])[12]).toBeNull()
  expect(monthLabel('2026-09')).toBe('2026년 9월')
})
