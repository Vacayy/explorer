export interface PeerSource {
  url: string
  claim: string
  verification: string
  period?: string
  publishedAt?: string
}
export interface PeerGroup {
  id: string
  name: string
  scope: 'product' | 'value_chain'
  interpretation: string
}
export interface PeerCompany {
  code: string
  name: string
  asOf: string
  products: string[]
  aliases: string[]
  groupIds: string[]
  caveats: string[]
  sources: PeerSource[]
}
export interface PeerCatalog {
  version: string
  asOf: string
  groups: PeerGroup[]
  companies: PeerCompany[]
}

export interface PeerPriceSnapshot {
  version: string
  asOf: string
  collectedAt: string
  sourceUrl: string
  sourceHash: string
  field: 'regularMarketClosingPrice'
  session: 'KRX_REGULAR'
  adjustmentStatus: 'unverified'
  dates: string[]
  prices: Record<string, (number | null)[]>
  qualityIssues: { code: string; date: string; reason: string; sourceUrl: string }[]
  caveats: string[]
}
export interface PeerMemberPerformance {
  code: string
  name: string
  returnPct: number | null
  peerReturnPct: number | null
  excessPp: number | null
  rank: number | null
}
export interface PeerGroupPerformance {
  id: string
  name: string
  scope: PeerGroup['scope']
  memberCount: number
  coveredCount: number
  returnPct: number | null
  medianPct: number | null
  risingCount: number | null
  path: number[] | null
  members: PeerMemberPerformance[]
  missingCodes: string[]
}
