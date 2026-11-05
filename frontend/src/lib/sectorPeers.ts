import { peerChildren } from '@/lib/peerPresets'
import { normalizedPeerPath } from '@/lib/peerPerformance'
import type { SectorPeerEntry } from '@/types'
import type { PeerCatalog, PeerPriceSnapshot } from '@/types/peer'

/** 섹터와 이어진 '이 산업의 데이터' 화면 — 데이터가 그 섹터를 실제로 다루는 것만 */
export type SectorDataLink = 'trade' | 'taiwan' | 'valuechain' | 'usSeason'
export const SECTOR_DATA_LINKS: Readonly<Record<SectorDataLink, { label: string; to: string }>> = {
  trade: { label: '수출입', to: '/follow/trade' },
  taiwan: { label: '대만 공급망', to: '/follow/taiwan' },
  valuechain: { label: '밸류체인', to: '/value-chain' },
  usSeason: { label: '미국 실적 시즌', to: '/follow/transcripts?view=season' },
}
const NO_TRADE = new Set(['금융', '지주·기타', 'IT서비스·SW', '통신', '미디어·엔터·게임', '건설·부동산'])
const SUPPLY_CHAIN = new Set(['반도체·전자부품'])
const AI_INFRA = new Set(['반도체·전자부품', '전력·에너지'])

export function sectorDataLinks(sector: string): SectorDataLink[] {
  const out: SectorDataLink[] = []
  if (!NO_TRADE.has(sector)) out.push('trade')
  if (SUPPLY_CHAIN.has(sector)) out.push('taiwan')
  if (AI_INFRA.has(sector)) out.push('valuechain', 'usSeason')
  return out
}

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

/** 그룹 구성 종목 코드 */
export const groupCodes = (catalog: PeerCatalog, groupId: string) =>
  catalog.companies.filter(c => c.groupIds.includes(groupId)).map(c => c.code)

function median(values: number[]): number | null {
  if (!values.length) return null
  const s = [...values].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

/**
 * 그룹 중앙값 경로 — 기간 시작=100. 가격이 없는 종목은 빼고(§4.28 부분) 남은 종목의 날짜별 중앙값.
 * 관측 종목 수(covered)를 같이 돌려 화면이 '평균에 들어간 수'를 밝힐 수 있게 한다.
 */
export function groupMedianPath(snapshot: PeerPriceSnapshot, codes: readonly string[], days: number): { path: number[] | null; covered: number } {
  const paths = codes.map(c => normalizedPeerPath(snapshot, c, days)).filter((p): p is number[] => !!p)
  if (!paths.length) return { path: null, covered: 0 }
  return { path: paths[0].map((_, i) => median(paths.map(p => p[i]))!), covered: paths.length }
}

/** 그룹 n일 중앙 수익률(%) — 중앙값 경로의 끝 − 100 */
export function groupMedianReturn(snapshot: PeerPriceSnapshot, codes: readonly string[], days: number): number | null {
  const { path } = groupMedianPath(snapshot, codes, days)
  return path ? path[path.length - 1] - 100 : null
}

/** 종목 n일 수익률(%) — 가격이 없으면 null */
export function memberReturn(snapshot: PeerPriceSnapshot, code: string, days: number): number | null {
  const p = normalizedPeerPath(snapshot, code, days)
  return p ? p[p.length - 1] - 100 : null
}

/** 섹터 줄 정렬 — 기본은 시총, 칩으로 장기 RS · 단기 RS · 5일. null은 뒤 */
export type SectorSort = 'cap' | 'long' | 'short' | 'chg5'
export function parseSectorSort(v: string | null): SectorSort {
  return v === 'long' || v === 'short' || v === 'chg5' ? v : 'cap'
}
export function sortSectors<T extends { market_cap: number; rs_long: number | null; rs_short: number | null; chg_5d: number }>(rows: readonly T[], sort: SectorSort): T[] {
  const key = (r: T) => sort === 'long' ? r.rs_long : sort === 'short' ? r.rs_short : sort === 'chg5' ? r.chg_5d : r.market_cap
  return [...rows].sort((a, b) => (key(b) ?? -Infinity) - (key(a) ?? -Infinity))
}

/** 단기 RS 흐름 — 3주 전 → 지금. 궤적이 비면 지금 값만 */
export function shortRsTrail(g: { rs_short: number | null; trail: readonly { weeks_ago: number; rs_short: number | null }[] }): { label: string; value: number | null }[] {
  const past = [...g.trail].sort((a, b) => b.weeks_ago - a.weeks_ago).map(t => ({ label: `${t.weeks_ago}주 전`, value: t.rs_short }))
  return [...past, { label: '지금', value: g.rs_short }]
}
