import { expect, it } from 'vitest'
import raw from '@/data/peer-catalog.json'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { navigatePeerLayer, peerLayer, peerIndustry, peerLayerGroups } from '@/lib/peerNavigation'
const catalog = parsePeerCatalog(raw)
it('defaults to industries but preserves existing direct links', () => {
  expect(peerLayer(new URLSearchParams())).toBe('industries')
  expect(peerLayer(new URLSearchParams('group=test_socket'))).toBe('peers')
  expect(peerLayer(new URLSearchParams('overview=candidates'))).toBe('peers')
  expect(peerLayer(new URLSearchParams('layer=unknown'))).toBe('unknown')
  expect(peerIndustry(catalog, new URLSearchParams('group=test_socket'))).toBe('semiconductor_value_chain')
})
it('keeps reviewed hierarchy and standalone product groups without inventing children', () => {
  expect(peerLayerGroups(catalog, 'industries', '').length).toBe(10)
  expect(peerLayerGroups(catalog, 'businesses', 'power_infrastructure').map(g => g.id).sort()).toEqual(['power_cable', 'power_transformer', 'switchgear'])
  expect(peerLayerGroups(catalog, 'businesses', 'bank_financial_holding').map(g => g.id)).toEqual(['bank_financial_holding'])
  expect(peerLayerGroups(catalog, 'businesses', 'invalid')).toEqual([])
  expect(peerLayerGroups(catalog, 'businesses', 'all').every(g => g.scope === 'product')).toBe(true)
})
it('drilling preserves period and clears stale comparison overrides without mutating history', () => {
  const previous = new URLSearchParams('days=60&focus=nuclear_value_chain&stock=425420&benchmark=battery_cell&settings=1&overview=candidates')
  const next = navigatePeerLayer(previous, 'businesses', 'power_infrastructure')
  expect(next.toString()).toBe('days=60&layer=businesses&industry=power_infrastructure')
  expect(previous.get('stock')).toBe('425420')
  expect(navigatePeerLayer(next, 'peers', 'power_infrastructure', 'power_transformer').get('group')).toBe('power_transformer')
})
