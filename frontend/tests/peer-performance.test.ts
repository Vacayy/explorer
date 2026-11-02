import { expect, it } from 'vitest'
import { computePeerPerformance, normalizedPeerPath, parsePeerPrices, groupOverlap } from '@/lib/peerPerformance'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import catalogRaw from '@/data/peer-catalog.json'
import pricesRaw from '@/data/peer-prices.json'
import type { PeerCatalog, PeerPriceSnapshot } from '@/types/peer'

const catalog: PeerCatalog = {
  version: 'test', asOf: '2026-11-01',
  groups: [{ id: 'g', name: '그룹', scope: 'product', interpretation: 'test' }, { id: 'solo', name: '단독', scope: 'product', interpretation: 'test' }],
  companies: ['000001', '000002', '000003'].map((code, index) => ({
    code, name: code, asOf: '2026-11-01', aliases: [], products: ['test'], groupIds: index === 0 ? ['g', 'solo'] : ['g'], caveats: [], sources: [{ url: 'https://example.com', claim: 'test', verification: 'test' }],
  })),
}
const snapshot: PeerPriceSnapshot = {
  version: 'test', asOf: '2026-10-30', collectedAt: '2026-11-01T01:00:00Z', sourceUrl: 'https://example.com', sourceHash: 'a'.repeat(64),
  field: 'regularMarketClosingPrice', session: 'KRX_REGULAR', adjustmentStatus: 'unverified',
  dates: ['2026-10-23', '2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30'],
  qualityIssues: [],
  prices: { '000001': [100, 105, 102, 108, 110, 120], '000002': [200, 210, 205, 210, 210, 220], '000003': [100, 90, 95, 98, 100, 100] }, caveats: [],
}

it('uses start-date equal weights and self-excluded peers with matching table/chart endpoints', () => {
  const result = computePeerPerformance(catalog, snapshot, 5)[0]
  expect(result.returnPct).toBeCloseTo(10)
  expect(result.path?.at(-1)).toBeCloseTo(110)
  expect(result.medianPct).toBeCloseTo(10)
  expect(result.risingCount).toBe(2)
  expect(result.members[0].returnPct).toBeCloseTo(20)
  expect(result.members[0].peerReturnPct).toBeCloseTo(5)
  expect(result.members[0].excessPp).toBeCloseTo(15)
  expect(result.members[0].rank).toBe(1)
  expect(groupOverlap(catalog, 'g', 'solo')).toBe(1)
})

it('never shrinks the benchmark for missing observations, even between valid endpoints', () => {
  const incomplete = structuredClone(snapshot); incomplete.prices['000002'][2] = null
  const result = computePeerPerformance(catalog, incomplete, 5)[0]
  expect(result.returnPct).toBeNull()
  expect(result.path).toBeNull()
  expect(result.coveredCount).toBe(2)
  expect(result.missingCodes).toEqual(['000002'])
  expect(result.members.every(row => row.peerReturnPct === null && row.excessPp === null && row.rank === null)).toBe(true)
  expect(result.members.find(row => row.code === '000001')?.returnPct).toBeCloseTo(20)
})

it('handles singletons, insufficient history, ties, and invalid windows', () => {
  const solo = computePeerPerformance(catalog, snapshot, 5)[1]
  expect(solo.members[0].excessPp).toBeNull()
  expect(normalizedPeerPath(snapshot, '000001', 20)).toBeNull()
  expect(normalizedPeerPath(snapshot, '000001', 6)).toBeNull()
  const tied = structuredClone(snapshot); tied.prices['000002'][5] = 240
  expect(computePeerPerformance(catalog, tied, 5)[0].members.map(row => row.rank)).toEqual([1, 1, 3])
})

it('rejects duplicate dates, bad lengths, zero prices and wrong session fields', () => {
  expect(() => parsePeerPrices({ ...snapshot, dates: [...snapshot.dates].reverse() })).toThrow()
  expect(() => parsePeerPrices({ ...snapshot, qualityIssues: [],
  prices: { '000001': [100] } })).toThrow()
  const bad = structuredClone(snapshot); bad.prices['000001'][0] = 0
  expect(() => parsePeerPrices(bad)).toThrow()
  expect(() => parsePeerPrices({ ...snapshot, field: 'closingPrice' })).toThrow()
})

it('reproduces independently audited real figures and complete catalog coverage', () => {
  const actual = parsePeerPrices(pricesRaw), definitions = parsePeerCatalog(catalogRaw)
  expect(definitions.companies).toHaveLength(98)
  expect(definitions.companies.every(company => actual.prices[company.code]?.length === 61)).toBe(true)
  for (const days of [5, 20, 60]) {
    const results = computePeerPerformance(definitions, actual, days)
    const blocked = days === 5 ? [] : days === 20 ? ['nuclear_maintenance', 'nuclear_value_chain'] : ['battery_cathode', 'battery_value_chain', 'nuclear_maintenance', 'nuclear_value_chain']
    expect(results.filter(group => group.missingCodes.length > 0).map(group => group.id).sort()).toEqual(blocked)
    for (const group of results.filter(group => group.path)) expect(group.path!.at(-1)! - 100).toBeCloseTo(group.returnPct!, 8)
  }
  const socket = computePeerPerformance(definitions, actual, 20).find(group => group.id === 'test_socket')!
  expect(socket.members.find(row => row.code === '425420')!.excessPp).toBeCloseTo(62.777542, 5)
  const deposition = computePeerPerformance(definitions, actual, 5).find(group => group.id === 'deposition')!
  expect(deposition.members.find(row => row.code === '084370')!.excessPp).toBeCloseTo(2.308742, 5)
})


it('blocks a known reference-price discontinuity only when the window crosses it', () => {
  const affected = structuredClone(snapshot)
  affected.qualityIssues = [{ code: '000001', date: '2026-10-26', reason: 'reference reset', sourceUrl: 'https://example.com' }]
  expect(normalizedPeerPath(affected, '000001', 5)).toBeNull()
  expect(computePeerPerformance(catalog, affected, 5)[0].returnPct).toBeNull()
  affected.qualityIssues[0].date = '2026-10-23'
  expect(normalizedPeerPath(affected, '000001', 5)).not.toBeNull()
})
