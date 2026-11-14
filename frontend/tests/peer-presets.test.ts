import { expect, it } from 'vitest'
import catalog from '@/data/peer-catalog.json'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { peerChildren, peerParent } from '@/lib/peerPresets'
/** 비교 기준 = 상위 산업군이 있으면 그것, 없으면 자기 자신 */
const baseline = (id: string) => peerParent(data, id) ?? id
const data = parsePeerCatalog(catalog)

it('uses business parent groups and does not substitute another industry for a top-level group', () => {
  expect(baseline('power_transformer')).toBe('power_infrastructure')
  expect(baseline('test_socket')).toBe('semiconductor_value_chain')
  expect(baseline('power_infrastructure')).toBe('power_infrastructure')
  expect(baseline('bank_financial_holding')).toBe('bank_financial_holding')
  expect(peerChildren(data, 'power_infrastructure').map(group => group.id).sort()).toEqual(['power_cable', 'power_transformer', 'switchgear'])
})
it('compares nuclear and shipbuilding product groups against their own value chains', () => {
  expect(baseline('nuclear_value_chain')).toBe('nuclear_value_chain')
  for (const parent of ['nuclear_value_chain', 'shipbuilding']) {
    const children = peerChildren(data, parent)
    expect(children.length).toBeGreaterThan(1)
    for (const child of children) expect(baseline(child.id)).toBe(parent)
  }
  // Adding an industry preset must not displace beauty from automatic parent selection.
  expect(baseline('cosmetics_odm')).toBe('beauty_value_chain')
})
