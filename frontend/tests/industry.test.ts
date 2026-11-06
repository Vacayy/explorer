import { expect, it } from 'vitest'
import catalogRaw from '@/data/peer-catalog.json'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { sectorOfPeerGroup, sectorPeerGroups } from '@/lib/sectorPeers'
import { SECTOR_PEERS_FIXTURE, sectorEntry } from './fixtures/sectorPeers'
import { creditGroupMedians, defaultCreditPicks, parseCreditRange, sliceByRange } from '@/lib/credit'
import { monthLabel, movingAverage, parseTradeGridSort, rankTradeGrid } from '@/lib/trade'
import type { CreditRow, TradeFollowRow } from '@/types'

const catalog = parsePeerCatalog(catalogRaw)

it('server sector → peer links point at real catalog groups and expand parents to their product groups', () => {
  const ids = new Set(catalog.groups.map(g => g.id))
  for (const e of SECTOR_PEERS_FIXTURE.sectors) for (const l of e.links) expect(ids.has(l.group_id), `${e.sector} → ${l.group_id}`).toBe(true)
  const semis = sectorPeerGroups(catalog, sectorEntry('반도체·전자부품'))
  expect(semis.top).toEqual(['semiconductor_value_chain'])
  expect(semis.all.length).toBeGreaterThan(10)
  expect(semis.all[0]).toBe('semiconductor_value_chain')
  expect(new Set(semis.all).size).toBe(semis.all.length)
  const power = sectorPeerGroups(catalog, sectorEntry('전력·에너지'))
  expect(power.all).toContain('power_transformer')
  expect(power.all).toContain('nuclear_equipment')
  expect(sectorPeerGroups(catalog, sectorEntry('기계·장비')).partial).toBe(true)
  expect(sectorPeerGroups(catalog, sectorEntry('바이오·헬스케어'))).toEqual({ top: [], all: [], partial: false, note: null })
  expect(sectorPeerGroups(catalog, undefined)).toEqual({ top: [], all: [], partial: false, note: null })
  const unknown = { sector: 'x', partial: false, note: null, links: [{ ...sectorEntry('금융')!.links[0], group_id: 'absent' }] }
  expect(sectorPeerGroups(catalog, unknown).top).toEqual([])
})

it('peer group → sector prefers a direct link, then a parent chain; human links before auto suggestions', () => {
  const sectors = SECTOR_PEERS_FIXTURE.sectors
  expect(sectorOfPeerGroup(catalog, sectors, 'package_substrate')).toBe('반도체·전자부품')
  expect(sectorOfPeerGroup(catalog, sectors, 'robotics_automation')).toBe('기계·장비')
  expect(sectorOfPeerGroup(catalog, sectors, 'nuclear_equipment')).toBe('전력·에너지')
  expect(sectorOfPeerGroup(catalog, sectors, 'power_transformer')).toBe('전력·에너지')
  const auto = { sector: '가상', partial: false, note: null, links: [{ ...sectorEntry('금융')!.links[0], source: 'auto' as const }] }
  expect(sectorOfPeerGroup(catalog, [auto, ...sectors], 'bank_financial_holding')).toBe('금융')
  expect(sectorOfPeerGroup(catalog, [], 'bank_financial_holding')).toBeNull()
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
