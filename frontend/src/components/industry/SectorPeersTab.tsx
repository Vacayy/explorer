import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Search } from "lucide-react"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { Band, FillNote, FillSkeleton, MarketCard } from "@/components/home/MarketFrame"
import { FillArea } from "@/components/shared/Bounded"
import { PeerGroupPanel } from "@/components/peers/PeerGroupPanel"
import { Chip } from "@/components/industry/sectorParts"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useIsMobile } from "@/hooks/use-mobile"
import { usePeerRuntime } from "@/hooks/usePeerRuntime"
import { useSectorPeerList } from "@/hooks/useSectorView"
import { selectPeerGroup } from "@/lib/peerFrame"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { SectorPeerGroupRow } from "@/types"

/**
 * 섹터 화면 › Peer 그룹 탭 (ia-redesign §4.35·§4.12, 시안 Sector-Peers, D-327 안 A — 옛 탐색 › Peer 그룹 본체).
 * 왼쪽 하위 그룹 목록(그룹 · 종목 수 · 60거래일 중앙값, 찾기 URL q) | 오른쪽 고른 그룹 본문(PeerGroupPanel). 두 칸 높이 760 고정.
 * 폰: 목록만 두고, 그룹을 고르면 아래 시트로 본문을 연다(group을 지우면 닫힘).
 * 원천: 하위 그룹 = GET /api/spine/industry/{sector}/peers, 본문 = Peer 게시본(/api/peers/runtime).
 */
export default function SectorPeersTab({ sector }: { sector: string }) {
  const list = useSectorPeerList(sector)
  const runtime = usePeerRuntime()
  const mobile = useIsMobile()
  const [params, setParams] = useSearchParams()
  const q = (params.get("q") ?? "").trim()
  const groups = useMemo(() => [...(list.data?.groups ?? [])].sort((a, b) => (b.med_60d ?? -Infinity) - (a.med_60d ?? -Infinity)), [list.data])
  const catalog = runtime.data?.catalog
  const shown = useMemo(() => !q ? groups : groups.filter(g => g.name.includes(q) || (catalog?.companies ?? []).some(c => c.groupIds.includes(g.id) && (c.name.includes(q) || c.code === q || c.products.some(p => p.includes(q))))), [groups, q, catalog])
  const requested = params.get("group")
  const groupId = requested ?? (mobile ? null : groups[0]?.id ?? null)
  const known = !!groupId && groups.some(g => g.id === groupId)
  const pick = (id: string | null) => setParams(prev => { const n = selectPeerGroup(prev, id ?? ""); if (!id) n.delete("group"); return n })
  const setQ = (v: string) => setParams(prev => { const n = new URLSearchParams(prev); if (v) n.set("q", v); else n.delete("q"); return n }, { replace: true })
  const tops = groups.filter(g => !g.parent)

  const left = <MarketCard band="sectorPeers" label="sector.peerlist">
    <BlockHead section title="하위 그룹" sub={list.data ? `${groups.length} · 60거래일 중앙값 순` : " "} />
    <label className="relative flex h-8 shrink-0 items-center">
      <Search aria-hidden="true" className="pointer-events-none absolute left-3 size-3.5 text-ink-3" />
      <Input type="search" aria-label="그룹·종목 찾기" value={params.get("q") ?? ""} onChange={e => setQ(e.target.value)} placeholder="그룹·종목 찾기"
        className="h-8 rounded-full border-0 bg-chip pl-8 text-[12.5px] shadow-none" />
    </label>
    {tops.length > 0 && <div className="flex shrink-0 flex-wrap gap-1.5">
      {tops.map(g => <Chip key={g.id}>{g.name} {g.members}사{g.partial && " · 부분"}{g.auto && " · 자동"}</Chip>)}
      {tops.some(g => g.scope === "value_chain") && <Chip kind="warn">직접 경쟁 아님</Chip>}
    </div>}
    {list.isError ? <BlockError message="하위 그룹을 불러오지 못했습니다" error={list.error} onRetry={() => void list.refetch()} />
      : !list.data ? <FillSkeleton rows={14} />
      : !groups.length ? <FillNote>이 업종엔 아직 Peer 그룹이 없습니다.</FillNote>
      : !shown.length ? <div role="status" className="flex flex-col gap-1 text-sm"><p>"{q}"이 들어간 그룹이 없습니다.</p><button type="button" className="self-start font-semibold hover:underline" onClick={() => setQ("")}>검색어 지우기</button></div>
      : <FillArea aria-label="하위 그룹 목록">{shown.map(g => <GroupRow key={g.id} g={g} on={g.id === groupId} onPick={() => pick(g.id)} />)}</FillArea>}
  </MarketCard>

  const body = runtime.isError ? <BlockError message="Peer 저장 자료를 불러오지 못했습니다" error={runtime.error} onRetry={() => void runtime.refetch()} />
    : !runtime.data || !list.data ? <FillSkeleton rows={14} />
    : !groups.length ? <FillNote>이 업종엔 아직 Peer 그룹이 없습니다.</FillNote>
    : !known ? <div role="status" className="flex flex-col gap-2 text-sm"><p>이 그룹은 이 섹터에 걸려 있지 않습니다.</p>
        <Link to={`/industry?q=${encodeURIComponent(catalog?.groups.find(g => g.id === groupId)?.name ?? groupId ?? "")}`} className="self-start font-semibold hover:underline">섹터 지도에서 찾기 ›</Link></div>
    : <PeerGroupPanel data={runtime.data} groupId={groupId!} path={pathOf(sector, groups, groupId!)} />

  if (mobile) return <>
    {left}
    <Sheet open={!!requested} onOpenChange={open => { if (!open) pick(null) }}>
      <SheetContent side="bottom" className="flex h-[88dvh] flex-col gap-3 px-4 pb-4">
        <SheetHeader className="px-0"><SheetTitle>{groups.find(g => g.id === requested)?.name ?? "Peer 그룹"}</SheetTitle><SheetDescription className="sr-only">고른 그룹의 성과 비교와 사업 근거</SheetDescription></SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3">{body}</div>
      </SheetContent>
    </Sheet>
  </>
  return <Band label="Peer 그룹" cells={[[4, left], [8, <MarketCard key="body" band="sectorPeers" label="sector.peerbody">{body}</MarketCard>]]} />
}

function GroupRow({ g, on, onPick }: { g: SectorPeerGroupRow; on: boolean; onPick: () => void }) {
  return <button type="button" aria-current={on ? "true" : undefined} onClick={onPick}
    className={cn("grid w-full grid-cols-[minmax(0,1fr)_26px_58px] items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] hover:bg-surface-2", on && "bg-chip font-semibold hover:bg-chip")}>
    <span className={cn("truncate", g.parent && "pl-0")}>{g.name}</span>
    <span className="text-right font-mono text-ink-3 tabular-nums">{g.members}</span>
    <span className={cn("text-right font-mono tabular-nums", tone(g.med_60d))}>{formatPercent(g.med_60d)}</span>
  </button>
}

/** 위치 — 섹터 › 상위 그룹 › 그룹 (상위 그룹 자신이면 섹터 › 그룹) */
function pathOf(sector: string, groups: SectorPeerGroupRow[], id: string) {
  const g = groups.find(x => x.id === id)!
  const parent = g.parent ? groups.find(x => x.id === g.parent) : null
  return [{ id: null, name: sector }, ...(parent ? [{ id: parent.id, name: parent.name }] : []), { id: g.id, name: g.name }]
}
