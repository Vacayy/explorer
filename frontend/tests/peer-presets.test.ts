import { expect, it } from 'vitest'
import catalog from '@/data/peer-catalog.json'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { peerBaseline, peerChildren, selectPeerPreset } from '@/lib/peerPresets'
const data = parsePeerCatalog(catalog)

it('uses business parent groups and does not substitute another industry for a top-level group', () => {
  expect(peerBaseline(data, 'power_transformer').id).toBe('power_infrastructure')
  expect(peerBaseline(data, 'test_socket').id).toBe('semiconductor_value_chain')
  expect(peerBaseline(data, 'power_infrastructure').id).toBe('power_infrastructure')
  expect(peerBaseline(data, 'bank_financial_holding').id).toBe('bank_financial_holding')
  expect(peerChildren(data, 'power_infrastructure').map(group => group.id).sort()).toEqual(['power_cable', 'power_transformer', 'switchgear'])
})
it('changing preset clears old overrides while preserving period and research filters', () => {
  const before = new URLSearchParams('group=test_socket&benchmark=battery_cell&stock=425420&settings=1&days=60&q=소켓&overview=candidates')
  const next = selectPeerPreset(before, 'power_infrastructure')
  expect(next.get('days')).toBe('60')
  expect(next.get('q')).toBe('소켓')
  expect(next.get('group')).toBe('power_infrastructure')
  for (const key of ['benchmark','stock','settings','overview']) expect(next.has(key)).toBe(false)
  expect(before.get('stock')).toBe('425420')
  expect(selectPeerPreset(next, '').get('overview')).toBe('groups')
})
