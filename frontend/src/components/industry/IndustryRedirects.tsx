import { Navigate, useLocation } from "react-router-dom"
import { Skeleton } from "@/components/ui/skeleton"
import { sectorPath } from "@/components/industry/sectorParts"
import { usePeerRuntime } from "@/hooks/usePeerRuntime"
import { useSectorPeers } from "@/hooks/useSectorMap"
import { groupForStocks, peerGroupParam } from "@/lib/peerFrame"
import { sectorOfPeerGroup } from "@/lib/sectorPeers"
import type { PeerCatalog } from "@/types/peer"
import type { SectorPeerEntry } from "@/types"

/** 옛 /map(산업·섹터) → 섹터 지도. ?view=map은 지도 보기, ?group=<섹터>는 그 섹터 화면 (D-327) */
export function MapRedirect() {
  const params = new URLSearchParams(useLocation().search)
  const group = params.get("group")
  const to = group ? sectorPath(group) : params.get("view") === "map" ? "/industry?v=map" : "/industry"
  return <Navigate to={to} replace />
}

/**
 * 옛 Peer 주소 → 섹터 화면 Peer 탭 (D-327 안 A). 순수 계산(테스트 대상).
 * - /discover/peers?group=X(옛 layer·industry 포함) · /analyze/compare?stocks=A,B(그 종목이 가장 많이 든 그룹·첫 종목)
 * - 그룹이 걸린 섹터가 있으면 /industry/<섹터>?tab=peers&group=X (view·stock·days는 그대로)
 * - 섹터에 매이지 않은 그룹은 섹터 지도 찾기 /industry?q=<그룹 이름>, 그룹을 모르면 /industry
 */
export function peerRedirectTarget(search: string, catalog: PeerCatalog, sectors: readonly SectorPeerEntry[]): string {
  const params = new URLSearchParams(search)
  let group = peerGroupParam(params)
  let stock = params.get("stock")
  const stocks = params.get("stocks")
  if (!group && stocks) {
    const codes = stocks.split(",").filter(Boolean)
    group = groupForStocks(catalog, codes) ?? ""
    if (group) stock = codes.find(code => catalog.companies.some(c => c.code === code && c.groupIds.includes(group))) ?? null
  }
  const known = catalog.groups.find(g => g.id === group)
  if (!known) return "/industry"
  const sector = sectorOfPeerGroup(catalog, sectors, known.id)
  if (!sector) return `/industry?q=${encodeURIComponent(known.name)}`
  const next = new URLSearchParams({ tab: "peers", group: known.id })
  for (const [k, v] of [["view", params.get("view")], ["stock", stock], ["days", params.get("days")]] as const) if (v) next.set(k, v)
  return sectorPath(sector, `?${next}`)
}

export function PeerRedirect() {
  const { search } = useLocation()
  const runtime = usePeerRuntime()
  const links = useSectorPeers()
  if (runtime.isError || links.isError) return <Navigate to="/industry" replace />
  if (!runtime.data || !links.data) return <div role="status" aria-label="Peer 그룹으로 옮기는 중" className="space-y-3"><Skeleton className="h-9 w-48" /><Skeleton className="h-[480px] w-full" /></div>
  return <Navigate to={peerRedirectTarget(search, runtime.data.catalog, links.data.sectors)} replace />
}
