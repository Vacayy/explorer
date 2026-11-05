import type { SectorPeerEntry, SectorPeerLink, SectorPeers } from '@/types'

// GET /api/spine/sector-map/peers 고정 응답 — 서버 초안 대응표(backend/pipeline/sector_peers.SEED)와 같은 연결
const link = (group_id: string, partial = false, source: SectorPeerLink['source'] = 'seed'): SectorPeerLink =>
  ({ group_id, group_name: group_id, scope: 'product', source, partial, members: 3, classified: 3, in_sector: 2, share: 0.667 })
const entry = (sector: string, ids: string[], partial = false, note: string | null = null): SectorPeerEntry =>
  ({ sector, partial, note, links: ids.map(id => link(id, partial)) })

export const SECTOR_PEERS_FIXTURE: SectorPeers = {
  catalog_as_of: '2026-11-04', auto_share: 0.6,
  sectors: [
    entry('2차전지·에너지소재', ['battery_value_chain']),
    entry('건설·부동산', ['plant_epc', 'nuclear_epc'], true, '플랜트·원전 건설만'),
    entry('금융', ['bank_financial_holding', 'securities_brokerage']),
    entry('기계·장비', ['robotics_automation'], true, '로봇·자동화만'),
    entry('바이오·헬스케어', []),
    entry('반도체·전자부품', ['semiconductor_value_chain']),
    entry('유통·소비재', ['beauty_value_chain'], true, '화장품만'),
    entry('전력·에너지', ['power_infrastructure', 'nuclear_value_chain']),
    entry('조선·해운·운송', ['shipbuilding']),
    entry('철강·금속', []),
    entry('항공·방산·우주', ['defense_value_chain']),
    entry('화학·소재', ['diversified_materials'], true, '반도체 소재 중심'),
  ],
}

export const sectorEntry = (sector: string) => SECTOR_PEERS_FIXTURE.sectors.find(e => e.sector === sector)
