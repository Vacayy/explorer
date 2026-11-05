import { expect, it } from 'vitest'
import { normalizedPeerPath, parsePeerPrices } from '@/lib/peerPerformance'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import catalogRaw from '@/data/peer-catalog.json'
import pricesRaw from '@/data/peer-prices.json'
import type { PeerPriceSnapshot } from '@/types/peer'

const snapshot: PeerPriceSnapshot = {
  version: 'test', asOf: '2026-10-30', collectedAt: '2026-11-01T01:00:00Z', sourceUrl: 'https://example.com', sourceHash: 'a'.repeat(64),
  field: 'regularMarketClosingPrice', session: 'KRX_REGULAR', adjustmentStatus: 'unverified',
  dates: ['2026-10-23', '2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30'],
  qualityIssues: [],
  prices: { '000001': [100, 105, 102, 108, 110, 120], '000002': [200, 210, 205, 210, 210, 220], '000003': [100, 90, 95, 98, 100, 100] }, caveats: [],
}

it('normalizes to 100 at the window start and rejects insufficient history or invalid windows', () => {
  expect(normalizedPeerPath(snapshot, '000001', 5)?.at(-1)).toBeCloseTo(120)
  expect(normalizedPeerPath(snapshot, '000001', 20)).toBeNull()
  expect(normalizedPeerPath(snapshot, '000001', 6)).toBeNull()
  const incomplete = structuredClone(snapshot); incomplete.prices['000002'][2] = null
  expect(normalizedPeerPath(incomplete, '000002', 5)).toBeNull()
})

it('rejects duplicate dates, bad lengths, zero prices and wrong session fields', () => {
  expect(() => parsePeerPrices({ ...snapshot, dates: [...snapshot.dates].reverse() })).toThrow()
  expect(() => parsePeerPrices({ ...snapshot, qualityIssues: [],
  prices: { '000001': [100] } })).toThrow()
  const bad = structuredClone(snapshot); bad.prices['000001'][0] = 0
  expect(() => parsePeerPrices(bad)).toThrow()
  expect(() => parsePeerPrices({ ...snapshot, field: 'closingPrice' })).toThrow()
})

it('ships complete catalog price coverage', () => {
  const actual = parsePeerPrices(pricesRaw), definitions = parsePeerCatalog(catalogRaw)
  expect(definitions.companies).toHaveLength(104)
  expect(definitions.companies.every(company => actual.prices[company.code]?.length === 61)).toBe(true)
})

it('blocks a known reference-price discontinuity only when the window crosses it', () => {
  const affected = structuredClone(snapshot)
  affected.qualityIssues = [{ code: '000001', date: '2026-10-26', reason: 'reference reset', sourceUrl: 'https://example.com' }]
  expect(normalizedPeerPath(affected, '000001', 5)).toBeNull()
  affected.qualityIssues[0].date = '2026-10-23'
  expect(normalizedPeerPath(affected, '000001', 5)).not.toBeNull()
})
