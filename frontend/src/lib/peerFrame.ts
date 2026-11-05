import { peerChildren, peerParent } from '@/lib/peerPresets'
import { normalizedPeerPath } from '@/lib/peerPerformance'
import type { PeerCatalog, PeerCompany, PeerPriceSnapshot } from '@/types/peer'

/**
 * 탐색 › Peer 그룹 — 성과 비교와 사업 근거가 같이 쓰는 틀의 계산 (ia-redesign §4.12·§4.28).
 * 두 보기는 같은 그룹·같은 종목·같은 순위를 본다. 가격이 없는 종목은 줄을 두고 숫자만 비우며, 평균은 관측된 종목만으로 내고 그 수를 같이 돌려준다.
 */
export type PeerView = 'performance' | 'research'
export type PeerDays = 5 | 20 | 60
export const PEER_DAYS: readonly PeerDays[] = [5, 20, 60]

export function peerView(params: URLSearchParams): PeerView {
  return params.get('view') === 'research' ? 'research' : 'performance'
}
/** 기본 60일 — 시안의 기본 보기 */
export function peerDays(params: URLSearchParams): PeerDays {
  const n = Number(params.get('days'))
  return n === 5 || n === 20 || n === 60 ? n : 60
}
/** 고른 그룹 — 옛 단계 링크(layer=businesses&industry=X)는 X를 그룹으로 본다 */
export function peerGroupParam(params: URLSearchParams): string {
  return params.get('group') ?? (params.get('layer') !== 'industries' ? params.get('industry') ?? '' : '')
}

/** 그룹 바꾸기 — 종목·옛 단계 값은 지우고 보기·기간·검색어는 둔다(§4.12 넘어가는 규칙) */
export function selectPeerGroup(previous: URLSearchParams, groupId: string): URLSearchParams {
  const next = new URLSearchParams(previous)
  for (const key of ['stock', 'stocks', 'layer', 'industry', 'benchmark', 'focus', 'overview', 'settings', 'scope']) next.delete(key)
  if (groupId) next.set('group', groupId)
  else next.delete('group')
  return next
}
/** 보기 바꾸기 — group·stock·days는 그대로 */
export function switchPeerView(previous: URLSearchParams, view: PeerView, stock?: string): URLSearchParams {
  const next = new URLSearchParams(previous)
  next.set('view', view)
  if (stock) next.set('stock', stock)
  return next
}

/** 근거 확인 수준 — 원문 대조 · 검색 요약만 · 링크만(본문 대조 전, verification에 link_only) */
export const sourceCheck = (verification: string): 'original' | 'snippet' | 'link' =>
  /link_only/i.test(verification) ? 'link' : /snippet/i.test(verification) ? 'snippet' : 'original'

/** 사업 근거 요약 — 원문 확인(검색 요약만·링크만 본 근거 제외) 수, 주의 수, 복합사업 여부 */
export function companyEvidence(company: PeerCompany) {
  return {
    verified: company.sources.filter(source => sourceCheck(source.verification) === 'original').length,
    caveats: company.caveats.length,
    composite: company.caveats.some(text => /복합\s?(사업|기업)/.test(text)),
  }
}

export const groupCompanies = (catalog: PeerCatalog, groupId: string) =>
  catalog.companies.filter(company => company.groupIds.includes(groupId))

export function memberReturnPct(snapshot: PeerPriceSnapshot, code: string, days: number): number | null {
  const path = normalizedPeerPath(snapshot, code, days)
  return path ? path[path.length - 1] - 100 : null
}

const mean = (values: number[]) => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null

export interface PeerMemberRow {
  code: string
  name: string
  products: string[]
  returns: Record<PeerDays, number | null>
  /** 20일 자기 제외 Peer 평균 대비(%p) — 다른 관측 종목이 없으면 null */
  excess20: number | null
  /** 고른 기간 순위 — 가격이 없으면 null */
  rank: number | null
  verified: number
  caveats: number
  composite: boolean
}

/** 구성 종목 줄 — 고른 기간 수익률 순, 가격 없는 종목은 맨 뒤(순위 없음) */
export function peerMemberRows(catalog: PeerCatalog, snapshot: PeerPriceSnapshot, groupId: string, days: PeerDays): PeerMemberRow[] {
  const companies = groupCompanies(catalog, groupId)
  const rows = companies.map(company => {
    const returns = Object.fromEntries(PEER_DAYS.map(d => [d, memberReturnPct(snapshot, company.code, d)])) as Record<PeerDays, number | null>
    return { code: company.code, name: company.name, products: company.products, returns, excess20: null as number | null, rank: null as number | null, ...companyEvidence(company) }
  })
  for (const row of rows) {
    const others = rows.filter(other => other !== row && other.returns[20] !== null).map(other => other.returns[20]!)
    const peer = mean(others)
    row.excess20 = row.returns[20] !== null && peer !== null ? row.returns[20] - peer : null
  }
  const sorted = [...rows].sort((a, b) => (b.returns[days] ?? -Infinity) - (a.returns[days] ?? -Infinity) || a.code.localeCompare(b.code))
  for (const row of sorted) {
    const value = row.returns[days]
    row.rank = value === null ? null : 1 + sorted.filter(other => other.returns[days] !== null && other.returns[days]! > value + 1e-10).length
  }
  return sorted
}

/** 그룹 동일가중 평균 — 관측된 종목만, covered = 평균에 들어간 수 */
export function groupAverage(rows: readonly PeerMemberRow[], days: PeerDays): { value: number | null; covered: number } {
  const values = rows.map(row => row.returns[days]).filter((v): v is number => v !== null)
  return { value: mean(values), covered: values.length }
}
export function groupAveragePath(snapshot: PeerPriceSnapshot, codes: readonly string[], days: number): number[] | null {
  const paths = codes.map(code => normalizedPeerPath(snapshot, code, days)).filter((p): p is number[] => !!p)
  return paths.length ? paths[0].map((_, i) => mean(paths.map(p => p[i]))!) : null
}

export interface PeerGroupSummary {
  memberCount: number
  scope: 'product' | 'value_chain'
  parent: { id: string; name: string; memberCount: number; avg20: number | null } | null
  avg: Record<PeerDays, number | null>
  covered: number
  vsParent20: number | null
  verifiedCompanies: number
  caveats: number
  lastChecked: string | null
}

export function peerGroupSummary(catalog: PeerCatalog, snapshot: PeerPriceSnapshot, groupId: string): PeerGroupSummary | null {
  const group = catalog.groups.find(item => item.id === groupId)
  if (!group) return null
  const rows = peerMemberRows(catalog, snapshot, groupId, 60)
  const avg = Object.fromEntries(PEER_DAYS.map(d => [d, groupAverage(rows, d).value])) as Record<PeerDays, number | null>
  const parentId = peerParent(catalog, groupId)
  const parentGroup = parentId ? catalog.groups.find(item => item.id === parentId) : undefined
  const parent = parentGroup ? (() => {
    const parentRows = peerMemberRows(catalog, snapshot, parentGroup.id, 20)
    return { id: parentGroup.id, name: parentGroup.name, memberCount: parentRows.length, avg20: groupAverage(parentRows, 20).value }
  })() : null
  const companies = groupCompanies(catalog, groupId)
  return {
    memberCount: rows.length, scope: group.scope, parent, avg, covered: groupAverage(rows, 60).covered,
    vsParent20: avg[20] !== null && parent?.avg20 != null ? avg[20] - parent.avg20 : null,
    verifiedCompanies: rows.filter(row => row.verified > 0).length,
    caveats: rows.reduce((sum, row) => sum + row.caveats, 0),
    lastChecked: companies.reduce<string | null>((latest, company) => !latest || company.asOf > latest ? company.asOf : latest, null),
  }
}

export interface PeerListItem { id: string; name: string; memberCount: number; return20: number | null }
const listItem = (catalog: PeerCatalog, snapshot: PeerPriceSnapshot, id: string): PeerListItem => {
  const rows = peerMemberRows(catalog, snapshot, id, 20)
  return { id, name: catalog.groups.find(group => group.id === id)?.name ?? id, memberCount: rows.length, return20: groupAverage(rows, 20).value }
}
const by20 = (a: PeerListItem, b: PeerListItem) => (b.return20 ?? -Infinity) - (a.return20 ?? -Infinity) || a.name.localeCompare(b.name, 'ko')

/** 업종 = 상위 그룹이 없는 그룹(밸류체인·단독 관찰군) */
export function peerIndustryOf(catalog: PeerCatalog, groupId: string): string | null {
  if (!catalog.groups.some(group => group.id === groupId)) return null
  return peerParent(catalog, groupId) ?? groupId
}

/**
 * 왼쪽 그룹 찾기 — 지금 업종(펼침, 사업군은 20일 순)과 '다른 업종'(20일 순).
 * 검색어는 그룹 이름 또는 구성 기업(이름·코드·별칭·제품)에 걸린 그룹만 남긴다. 성과 비교 구성원은 바꾸지 않는다.
 */
export function peerFinder(catalog: PeerCatalog, snapshot: PeerPriceSnapshot, groupId: string, query: string) {
  const needle = query.trim().toLocaleLowerCase('ko-KR')
  const hit = (id: string) => {
    if (!needle) return true
    const group = catalog.groups.find(item => item.id === id)
    if (group?.name.toLocaleLowerCase('ko-KR').includes(needle)) return true
    return groupCompanies(catalog, id).some(company => [company.name, company.code, ...company.aliases, ...company.products].join(' ').toLocaleLowerCase('ko-KR').includes(needle))
  }
  const tops = catalog.groups.filter(group => !peerParent(catalog, group.id)).map(group => group.id)
  const current = peerIndustryOf(catalog, groupId)
  const children = (id: string) => peerChildren(catalog, id).map(child => child.id).filter(hit).map(child => listItem(catalog, snapshot, child)).sort(by20)
  const open = current ? { industry: listItem(catalog, snapshot, current), children: children(current) } : null
  const others = tops.filter(id => id !== current)
    .filter(id => hit(id) || (needle && peerChildren(catalog, id).some(child => hit(child.id))))
    .map(id => ({ ...listItem(catalog, snapshot, id), children: needle ? children(id) : [] })).sort(by20)
  const empty = !!needle && !(open && (hit(open.industry.id) || open.children.length)) && !others.length
  return { open, others, empty }
}

/** /analyze/compare?stocks=A,B 에서 넘어온 종목들 → 가장 많이 함께 든(같으면 작은) 그룹 */
export function groupForStocks(catalog: PeerCatalog, codes: readonly string[]): string | null {
  const known = codes.filter(code => catalog.companies.some(company => company.code === code))
  if (!known.length) return null
  let best: { id: string; hits: number; size: number } | null = null
  for (const group of catalog.groups) {
    const members = groupCompanies(catalog, group.id)
    const hits = known.filter(code => members.some(company => company.code === code)).length
    if (!hits) continue
    const candidate = { id: group.id, hits, size: members.length }
    if (!best || hits > best.hits || (hits === best.hits && candidate.size < best.size)) best = candidate
  }
  return best?.id ?? null
}
