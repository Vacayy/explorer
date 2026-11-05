import type { PeerCatalog } from '@/types/peer'

/** Reviewed hierarchy parents, not return correlations or inferred competitors. */
const parents = ['power_infrastructure', 'semiconductor_value_chain', 'defense_value_chain',
  'shipbuilding', 'nuclear_value_chain', 'battery_value_chain', 'beauty_value_chain']

export function peerParent(catalog: PeerCatalog, groupId: string): string | undefined {
  const group = catalog.groups.find(item => item.id === groupId)
  if (!group || group.scope !== 'product') return undefined
  const members = catalog.companies.filter(company => company.groupIds.includes(groupId))
  return members.length ? parents.find(id => id !== groupId && catalog.groups.some(item => item.id === id && item.scope === 'value_chain') && members.every(company => company.groupIds.includes(id))) : undefined
}

export function peerChildren(catalog: PeerCatalog, groupId: string) {
  return catalog.groups.filter(group => peerParent(catalog, group.id) === groupId)
}
