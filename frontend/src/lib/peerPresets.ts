import type { PeerCatalog } from '@/types/peer'

/** Reviewed hierarchy candidates, not return correlations or inferred competitors. */
export const PEER_PRESETS = [
  'power_infrastructure', 'semiconductor_value_chain', 'defense_value_chain', 'shipbuilding', 'nuclear_value_chain',
  'battery_value_chain', 'beauty_value_chain', 'bank_financial_holding', 'securities_brokerage', 'plant_epc',
]
const parents = ['power_infrastructure', 'semiconductor_value_chain', 'defense_value_chain',
  'shipbuilding', 'nuclear_value_chain', 'battery_value_chain', 'beauty_value_chain']

export function peerParent(catalog: PeerCatalog, groupId: string): string | undefined {
  const group = catalog.groups.find(item => item.id === groupId)
  if (!group || group.scope !== 'product') return undefined
  const members = catalog.companies.filter(company => company.groupIds.includes(groupId))
  return members.length ? parents.find(id => id !== groupId && catalog.groups.some(item => item.id === id && item.scope === 'value_chain') && members.every(company => company.groupIds.includes(id))) : undefined
}

export function peerBaseline(catalog: PeerCatalog, groupId: string) {
  const parent = peerParent(catalog, groupId)
  return {
    id: parent ?? groupId,
    reason: parent ? '자동 기준 · 상위 산업군' : '자동 기준 · 구성 종목 동일가중 평균. 시장 지수는 아직 연결되지 않았습니다.',
  }
}

export function peerChildren(catalog: PeerCatalog, groupId: string) {
  return catalog.groups.filter(group => peerParent(catalog, group.id) === groupId)
}

export function selectPeerPreset(previous: URLSearchParams, groupId: string) {
  const next = new URLSearchParams(previous)
  for (const key of ['benchmark', 'stock', 'settings', 'overview']) next.delete(key)
  if (groupId) next.set('group', groupId)
  else { next.delete('group'); next.set('overview', 'groups') }
  return next
}
