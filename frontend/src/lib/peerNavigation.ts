import { PEER_PRESETS, peerChildren, peerParent } from '@/lib/peerPresets'
import type { PeerCatalog } from '@/types/peer'

export type PeerLayer = 'industries' | 'businesses' | 'peers'
export function peerLayer(params: URLSearchParams): string {
  return params.get('layer') ?? (params.has('group') || params.has('overview') ? 'peers' : 'industries')
}
export function peerIndustry(catalog: PeerCatalog, params: URLSearchParams): string {
  // Explicit selections, including invalid ones, must not be silently replaced.
  if (params.has('industry')) return params.get('industry')!
  const group = params.get('group')
  return group ? peerParent(catalog, group) ?? group : 'power_infrastructure'
}
export function peerLayerGroups(catalog: PeerCatalog, layer: string, industry: string) {
  if (layer === 'industries') return PEER_PRESETS.flatMap(id => catalog.groups.filter(group => group.id === id))
  if (industry === 'all') return catalog.groups.filter(group => group.scope === 'product')
  const parent = catalog.groups.find(group => group.id === industry)
  if (!parent) return []
  const children = peerChildren(catalog, industry)
  return children.length ? children : parent.scope === 'product' ? [parent] : []
}
export function navigatePeerLayer(previous: URLSearchParams, layer: PeerLayer, industry?: string, group?: string) {
  const next = new URLSearchParams(previous)
  for (const key of ['group', 'industry', 'benchmark', 'stock', 'settings', 'overview', 'scope', 'relative', 'focus']) next.delete(key)
  next.set('layer', layer)
  if (industry) next.set('industry', industry)
  if (group) next.set('group', group)
  return next
}
