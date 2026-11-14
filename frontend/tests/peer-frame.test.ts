import { expect, it } from 'vitest'
import raw from '@/data/peer-catalog.json'
import rawPrices from '@/data/peer-prices.json'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { parsePeerPrices } from '@/lib/peerPerformance'
import { companyEvidence, groupAverage, groupForStocks, peerDays, peerGroupParam, peerGroupSummary, peerMemberRows, peerView, selectPeerGroup, switchPeerView } from '@/lib/peerFrame'
import { sectorOfPeerGroup } from '@/lib/sectorPeers'
import { SECTOR_PEERS_FIXTURE } from './fixtures/sectorPeers'

const catalog = parsePeerCatalog(raw)
const prices = parsePeerPrices(rawPrices)

it('reads view, days (default 60) and group, mapping old layer links', () => {
  expect(peerView(new URLSearchParams())).toBe('performance')
  expect(peerView(new URLSearchParams('view=research'))).toBe('research')
  expect(peerDays(new URLSearchParams())).toBe(60)
  expect(peerDays(new URLSearchParams('days=7'))).toBe(60)
  expect(peerDays(new URLSearchParams('days=5'))).toBe(5)
  expect(peerGroupParam(new URLSearchParams('layer=businesses&industry=power_infrastructure'))).toBe('power_infrastructure')
  expect(peerGroupParam(new URLSearchParams('layer=industries&industry=power_infrastructure'))).toBe('')
})

it('changing group clears stock and legacy overrides; switching view keeps group, stock and days', () => {
  const before = new URLSearchParams('group=test_socket&stock=425420&days=20&view=research&q=소켓&benchmark=x&layer=peers')
  const next = selectPeerGroup(before, 'power_transformer')
  expect(next.toString()).toBe('group=power_transformer&days=20&view=research&q=%EC%86%8C%EC%BC%93')
  expect(before.get('stock')).toBe('425420')
  const view = switchPeerView(new URLSearchParams('group=a&stock=1&days=5'), 'research')
  expect(view.toString()).toBe('group=a&stock=1&days=5&view=research')
})

it('ranks members by the chosen period, puts missing prices last without a rank and excludes them from the average', () => {
  const rows = peerMemberRows(catalog, prices, 'battery_value_chain', 60)
  const missing = rows.find(row => row.code === '247540')!
  expect(missing.returns[60]).toBeNull()
  expect(missing.rank).toBeNull()
  expect(rows[rows.length - 1].code).toBe('247540')
  expect(rows.slice(0, 3).map(row => row.rank)).toEqual([1, 2, 3])
  const average = groupAverage(rows, 60)
  expect(average.covered).toBe(3)
  const valid = rows.filter(row => row.returns[60] !== null).map(row => row.returns[60]!)
  expect(average.value).toBeCloseTo(valid.reduce((a, b) => a + b, 0) / valid.length)
})

it('evidence counts exclude snippet-only sources and flag composite businesses', () => {
  const samsung = catalog.companies.find(c => c.code === '009150')!
  expect(companyEvidence(samsung).composite).toBe(true)
  const company = { ...samsung, sources: [{ ...samsung.sources[0], verification: 'primary_search_snippet_only' }, samsung.sources[0]], caveats: [] }
  expect(companyEvidence(company)).toEqual({ verified: 1, caveats: 0, composite: false })
})

it('summary compares the group against its parent industry over 20 days', () => {
  const summary = peerGroupSummary(catalog, prices, 'power_transformer')!
  expect(summary.memberCount).toBe(4)
  expect(summary.parent?.id).toBe('power_infrastructure')
  expect(summary.vsParent20).toBeCloseTo(summary.avg[20]! - summary.parent!.avg20!)
  expect(peerGroupSummary(catalog, prices, 'bank_financial_holding')!.parent).toBeNull()
  expect(peerGroupSummary(catalog, prices, 'nope')).toBeNull()
})

it('maps compared stocks to the group holding most of them and groups to sectors', () => {
  expect(groupForStocks(catalog, ['103590', '298040'])).toBe('power_transformer')
  expect(groupForStocks(catalog, ['999999'])).toBeNull()
  expect(sectorOfPeerGroup(catalog, SECTOR_PEERS_FIXTURE.sectors, 'package_substrate')).toBe('반도체·전자부품')
  expect(sectorOfPeerGroup(catalog, SECTOR_PEERS_FIXTURE.sectors, 'bank_financial_holding')).toBe('금융')
})
