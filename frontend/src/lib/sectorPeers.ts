import { peerChildren } from '@/lib/peerPresets'
import type { SectorPeerEntry } from '@/types'
import type { PeerCatalog } from '@/types/peer'

/**
 * 섹터에 걸린 그룹 — 서버 대응표(GET /api/spine/sector-map/peers)의 그룹(top)과 그 아래 제품 그룹까지 편 전체(all).
 * 상위 그룹(value_chain)은 그 아래 제품 그룹까지 함께 센다(peerChildren). 카탈로그에 없는 id는 버린다.
 */
export function sectorPeerGroups(catalog: PeerCatalog, entry: SectorPeerEntry | undefined): { top: string[]; all: string[]; partial: boolean; note: string | null } {
  if (!entry) return { top: [], all: [], partial: false, note: null }
  const known = new Set(catalog.groups.map(g => g.id))
  const top = entry.links.map(l => l.group_id).filter(id => known.has(id))
  const all: string[] = []
  for (const id of top) for (const g of [id, ...peerChildren(catalog, id).map(c => c.id)]) if (!all.includes(g)) all.push(g)
  return { top, all, partial: entry.partial, note: entry.note }
}

/**
 * Peer 그룹 → 섹터(역방향) — '이 그룹의 업황 보기'. 대응표에 그 그룹이 직접 있으면 그 섹터, 없으면 상위 그룹이 걸린 섹터.
 * 같은 단계에선 사람이 정한 연결(seed)이 자동 제안(auto)보다 먼저다.
 */
export function sectorOfPeerGroup(catalog: PeerCatalog, sectors: readonly SectorPeerEntry[], groupId: string): string | null {
  const auto = (e: SectorPeerEntry) => Number(e.links.some(l => l.source === 'auto'))
  const ordered = [...sectors].sort((a, b) => auto(a) - auto(b))
  return (ordered.find(e => e.links.some(l => l.group_id === groupId))
    ?? ordered.find(e => sectorPeerGroups(catalog, e).all.includes(groupId)))?.sector ?? null
}
