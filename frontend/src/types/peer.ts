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
