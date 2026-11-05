import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { MOBILE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery"
import MultiLineChart, { type LineConfig } from "@/components/charts/MultiLineChart"
import { HomeBlock } from "@/components/home/HomeSection"
import { BlockError, RowsSkeleton, tone } from "@/components/home/blockState"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useIsMobile } from "@/hooks/use-mobile"
import { usePeerRuntime } from "@/hooks/usePeerRuntime"
import { useSectorMap, useSectorPeers } from "@/hooks/useSectorMap"
import {
  SECTOR_DATA_LINKS, groupCodes, groupMedianPath, groupMedianReturn, memberReturn, parseSectorSort,
  sectorDataLinks, sectorPeerGroups, shortRsTrail, sortSectors, type SectorSort,
} from "@/lib/sectorPeers"
import { peerChildren } from "@/lib/peerPresets"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber, formatPercent } from "@/utils/format"
import type { SectorGroup, SectorPeerEntry } from "@/types"
import type { PeerCatalog, PeerPriceSnapshot } from "@/types/peer"

const RS_INFO = "산업 맵 18개 대분류의 상대강도입니다. 장기 RS = 11개월 수익률의 전 종목 대비 백분위(구조적 강도), 단기 RS = 1개월 수익률 백분위(지금 수급). 5일 = 시총 가중 5거래일 등락."
const CHART_DAYS = 60
const TABLE_DAYS = 20
const CHART_LINES = 5
const SORTS: { key: SectorSort; label: string }[] = [{ key: "long", label: "장기 RS" }, { key: "short", label: "단기 RS" }, { key: "chg5", label: "5일" }]

type Runtime = ReturnType<typeof usePeerRuntime>
type Links = ReturnType<typeof useSectorPeers>

/**
 * 산업 › 산업·섹터 기본 보기 (/map, 시안 Industry-Sector · Mobile-Industry, ia-redesign §4.7·§4.29).
 * 왼쪽 섹터 상대강도 표 | 오른쪽 고른 섹터 머리 → Peer 그룹(그룹 중앙값 60거래일, 시작=100) → 이 산업의 데이터 → 섹터 → Peer 그룹.
 * 모바일 = 정렬 칩 + 섹터 줄, 줄을 누르면 아래에서 섹터 시트. URL: group(고른 섹터) · sort(long·short·chg5, 없으면 시총).
 * 섹터 → Peer 그룹 대응은 서버 대응표(GET /api/spine/sector-map/peers, sector_peer_map + 자동 제안).
 */
export default function SectorBoard({ viewMenu }: { viewMenu?: React.ReactNode }) {
  const [params, setParams] = useSearchParams()
  const mobile = useIsMobile()
  const map = useSectorMap()
  const peers = usePeerRuntime()
  const links = useSectorPeers()
  const sort = parseSectorSort(params.get("sort"))
  const rows = useMemo(() => sortSectors(map.data?.groups ?? [], sort), [map.data, sort])
  const picked = params.get("group")
  const selected = rows.find(g => g.name === picked) ?? (mobile ? undefined : rows[0])
  const set = (key: string, value: string | null) => setParams(prev => { const n = new URLSearchParams(prev); if (value) n.set(key, value); else n.delete(key); return n }, { replace: true, preventScrollReset: true })
  const catalog = peers.data?.catalog
  const entryOf = (sector: string) => links.data?.sectors.find(e => e.sector === sector)

  const list = <HomeBlock label="sector.rs" title="산업·섹터 상대강도" info={RS_INFO} asOf={map.data?.as_of ?? null}
    actions={viewMenu} bodyClassName="p-0">
    {mobile && <div className="flex gap-1.5 border-b px-3 py-2" role="group" aria-label="정렬">
      {SORTS.map(s => <Button key={s.key} size="sm" variant={sort === s.key ? "secondary" : "outline"} aria-pressed={sort === s.key} className="h-7 text-xs"
        onClick={() => set("sort", sort === s.key ? null : s.key)}>{s.label}순</Button>)}
    </div>}
    {map.isPending ? <div className="p-3"><RowsSkeleton rows={12} /></div>
      : map.isError ? <div className="p-3"><BlockError message="섹터 상대강도를 불러오지 못했습니다" error={map.error} onRetry={() => void map.refetch()} /></div>
      : !rows.length ? <p role="status" className="p-3 text-sm text-muted-foreground">주가·섹터 데이터가 쌓이면 나타납니다.</p>
      : <SectorTable rows={rows} sort={sort} onSort={v => set("sort", v)} selected={selected?.name ?? null} mobile={mobile}
          peerCount={g => catalog && links.data ? sectorPeerGroups(catalog, entryOf(g)).all.length : null} onPick={g => set("group", g)} />}
  </HomeBlock>

  if (mobile) return <>
    {list}
    <Sheet open={!!picked && !!selected} onOpenChange={v => { if (!v) set("group", null) }}>
      <SheetContent side="bottom" className="max-h-[85dvh] overflow-y-auto">
        {selected && <SectorSheet g={selected} peers={peers} links={links} />}
      </SheetContent>
    </Sheet>
  </>

  return <div className="surface-grid grid items-start lg:grid-cols-[minmax(27rem,5fr)_minmax(0,7fr)]">
    {list}
    <div className="flex min-w-0 flex-col">
      {selected ? <SectorHead g={selected} /> : map.isPending ? <Skeleton className="h-24 w-full rounded-card" /> : null}
      {selected && <PeerBlock sector={selected.name} peers={peers} links={links} />}
      {selected && <DataLinks sector={selected.name} />}
      {map.data && <SectorPeerMap rows={map.data.groups} peers={peers} links={links} />}
    </div>
  </div>
}

function RsBar({ value, mobile }: { value: number | null; mobile?: boolean }) {
  // 모바일 = 숫자 아래 막대(열을 좁게)
  if (mobile) return <span className="flex flex-col items-start gap-1">
    <span className="font-mono tabular-nums">{value == null ? "-" : Math.round(value)}</span>
    <span className="h-1 w-12 overflow-hidden bg-muted" aria-hidden="true"><span className="block h-full bg-foreground/70" style={{ width: `${Math.max(2, value ?? 0)}%` }} /></span>
  </span>
  return <span className="flex items-center justify-end gap-2">
    <span className="h-1.5 w-10 overflow-hidden bg-muted xl:w-14" aria-hidden="true"><span className="block h-full bg-foreground/70" style={{ width: `${Math.max(2, value ?? 0)}%` }} /></span>
    <span className="w-7 text-right font-mono tabular-nums">{value == null ? "-" : Math.round(value)}</span>
  </span>
}

function SectorTable({ rows, sort, onSort, selected, mobile, peerCount, onPick }: {
  rows: SectorGroup[]; sort: SectorSort; onSort: (v: string | null) => void; selected: string | null; mobile: boolean
  peerCount: (sector: string) => number | null; onPick: (sector: string) => void
}) {
  // 머리를 누르면 그 열로 정렬, 다시 누르면 시총 순
  const head = (key: SectorSort, label: string, cls?: string) => <TableHead className={cn("h-8 text-[11px]", mobile && key !== "chg5" ? "text-left" : "text-right", cls)}>
    <Button variant="ghost" size="sm" className={cn("h-6 px-1 text-[11px] font-medium", sort === key ? "text-foreground" : "text-muted-foreground")}
      aria-pressed={sort === key} onClick={() => onSort(sort === key ? null : key)}>{label}</Button>
  </TableHead>
  return <Table className="text-[13px]">
    <TableHeader><TableRow>
      <TableHead className="h-8 pl-3 text-[11px]">섹터</TableHead>
      {!mobile && <TableHead className="h-8 text-right text-[11px]">시총</TableHead>}
      {head("long", "장기 RS")}{head("short", "단기 RS")}{head("chg5", "5일")}
      {!mobile && <TableHead className="h-8 pr-3 text-right text-[11px]">Peer</TableHead>}
    </TableRow></TableHeader>
    <TableBody>{rows.map(g => {
      const n = peerCount(g.name)
      return <TableRow key={g.name} data-sector-row aria-selected={selected === g.name} className={cn("cursor-pointer", selected === g.name && "bg-muted/60")} onClick={() => onPick(g.name)}>
        <TableCell className="whitespace-normal py-2 pl-3 font-medium">{g.name}
          {mobile && <span className="block text-[11px] font-normal text-muted-foreground">{formatKrw(g.market_cap)} · {formatNumber(g.stocks)}종목{n ? ` · Peer ${n}` : ""}</span>}</TableCell>
        {!mobile && <TableCell className="py-2 text-right font-mono tabular-nums">{formatKrw(g.market_cap)}</TableCell>}
        <TableCell className="py-2"><RsBar value={g.rs_long} mobile={mobile} /></TableCell>
        <TableCell className="py-2"><RsBar value={g.rs_short} mobile={mobile} /></TableCell>
        <TableCell className={cn("py-2 text-right font-mono tabular-nums", tone(g.chg_5d))}>{formatPercent(g.chg_5d)}</TableCell>
        {!mobile && <TableCell className="py-2 pr-3 text-right font-mono tabular-nums text-muted-foreground">{n ? n : "-"}</TableCell>}
      </TableRow>
    })}</TableBody>
  </Table>
}

function SectorHead({ g }: { g: SectorGroup }) {
  const trail = shortRsTrail(g)
  return <Card data-sector-head className="gap-1 rounded-[var(--radius-card)] px-4 py-4 shadow-none">
    <p className="text-xs text-muted-foreground">선택한 섹터</p>
    <h2 className="text-xl font-semibold">{g.name}</h2>
    <p className="text-[12.5px] text-ink-2">
      {formatNumber(g.stocks)}종목 · 시총 {formatKrw(g.market_cap)} · 장기 RS {g.rs_long ?? "-"} · 단기 RS {trail.map(t => `${t.label === "지금" ? "지금 " : `${t.label} `}${t.value ?? "-"}`).join(" → ")} · 5일 <span className={tone(g.chg_5d)}>{formatPercent(g.chg_5d)}</span>
    </p>
  </Card>
}

interface GroupStat { id: string; name: string; count: number; ret20: number | null; members: { name: string; ret: number | null }[] }

function groupStats(catalog: PeerCatalog, snapshot: PeerPriceSnapshot, ids: readonly string[]): GroupStat[] {
  return ids.map(id => {
    const codes = groupCodes(catalog, id)
    return {
      id, name: catalog.groups.find(x => x.id === id)?.name ?? id, count: codes.length,
      ret20: groupMedianReturn(snapshot, codes, TABLE_DAYS),
      members: codes.map(c => ({ name: catalog.companies.find(x => x.code === c)?.name ?? c, ret: memberReturn(snapshot, c, TABLE_DAYS) }))
        .sort((a, b) => (b.ret ?? -Infinity) - (a.ret ?? -Infinity)),
    }
  }).sort((a, b) => (b.ret20 ?? -Infinity) - (a.ret20 ?? -Infinity))
}

function PeerBlock({ sector, peers, links }: { sector: string; peers: Runtime; links: Links }) {
  const phone = useMediaQuery(MOBILE_QUERY)
  const d = peers.data
  const entry = links.data?.sectors.find(e => e.sector === sector)
  const linked = d && links.data ? sectorPeerGroups(d.catalog, entry) : null
  const chart = useMemo(() => {
    if (!d || !linked) return null
    const paths = linked.all
      .filter(id => groupCodes(d.catalog, id).length >= 2)
      .map(id => ({ id, name: d.catalog.groups.find(x => x.id === id)?.name ?? id, ...groupMedianPath(d.prices, groupCodes(d.catalog, id), CHART_DAYS) }))
      .filter(p => p.path)
      .sort((a, b) => b.path![b.path!.length - 1] - a.path![a.path!.length - 1])
      .slice(0, CHART_LINES)
    if (!paths.length) return null
    const dates = d.prices.dates.slice(-CHART_DAYS - 1)
    return { paths, data: dates.map((time, i) => ({ time, ...Object.fromEntries(paths.map(p => [p.id, p.path![i]])) })) }
    // linked는 sector·카탈로그·대응표로 정해진다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d, sector, links.data])
  const lines = useMemo<LineConfig[]>(() => {
    if (!chart) return []
    // 회색 시리즈 · 1위만 글자색 굵은 선 · 선 끝 라벨의 값만 등락색 (DESIGN_SYSTEM 차트 규칙)
    return chart.paths.map((p, i) => {
      const end = p.path![p.path!.length - 1] - 100
      return { key: p.id, label: p.name, color: i === 0 ? "--up" : "--series", lineWidth: i === 0 ? 2 : 1,
        endLabel: { name: p.name, value: formatPercent(end), tone: end > 0 ? "up" as const : end < 0 ? "down" as const : "flat" as const, strong: i === 0, accent: i === 0 } }
    }).reverse()
  }, [chart])
  const stats = d && linked ? groupStats(d.catalog, d.prices, linked.all) : []
  return <HomeBlock label="sector.peers" title="Peer 그룹"
    info={`이 섹터에 걸린 Peer 그룹입니다. 선은 그룹 구성 종목의 날짜별 중앙값(${CHART_DAYS}거래일 전 = 100), 상위 ${CHART_LINES}개 그룹만 그리고 1위를 굵게 표시합니다. 표는 ${TABLE_DAYS}거래일 중앙값 순입니다. 가격이 없는 종목은 계산에서 뺍니다.`}
    asOf={d?.prices.asOf ?? null}
    link={linked?.top.length ? { to: `/discover/peers?group=${linked.top[0]}`, label: "Peer 비교 열기" } : null}>
    {peers.isPending || links.isPending ? <div className="space-y-2"><Skeleton className="h-[260px] w-full" /><RowsSkeleton rows={4} head={false} /></div>
      : peers.isError || !d ? <BlockError message="Peer 그룹 가격을 불러오지 못했습니다" error={peers.error} onRetry={() => void peers.refetch()} />
      : links.isError ? <BlockError message="섹터 → Peer 대응표를 불러오지 못했습니다" error={links.error} onRetry={() => void links.refetch()} />
      : !linked?.all.length ? <p role="status" className="text-sm text-muted-foreground">이 업종엔 아직 Peer 그룹이 없습니다.</p>
      : <div className="space-y-3">
        {chart ? <MultiLineChart data={chart.data} lines={lines} height={260} showLegend={false} showLastValues={false} endLabels={phone ? undefined : 170} showLineTooltip formatValue={v => v.toFixed(1)} />
          : <p role="status" className="py-8 text-center text-sm text-muted-foreground">차트를 그릴 가격 관측이 없습니다.</p>}
        <Table className="text-[13px]">
          <TableHeader><TableRow>
            <TableHead className="h-8 px-1 text-[11px]">그룹</TableHead>
            <TableHead className="h-8 px-1 text-right text-[11px]">{TABLE_DAYS}일 중앙값</TableHead>
            <TableHead className="h-8 px-1 text-[11px]">구성 종목 {TABLE_DAYS}일</TableHead>
          </TableRow></TableHeader>
          <TableBody>{stats.slice(0, 8).map(s => <TableRow key={s.id}>
            <TableCell className="px-1 py-2 whitespace-nowrap"><Link to={`/discover/peers?group=${s.id}`} className="font-medium hover:underline">{s.name}</Link> <span className="text-[11px] text-muted-foreground">{s.count}종목</span></TableCell>
            <TableCell className={cn("px-1 py-2 text-right font-mono tabular-nums", tone(s.ret20))}>{formatPercent(s.ret20)}</TableCell>
            <TableCell className="max-w-0 truncate px-1 py-2 text-xs">{s.members.slice(0, 4).map((m, i) => <span key={m.name}>{i > 0 && " · "}{m.name} <span className={cn("font-mono tabular-nums", tone(m.ret))}>{formatPercent(m.ret)}</span></span>)}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
        {stats.length > 8 && linked.top[0] && <Link to={`/discover/peers?group=${linked.top[0]}`} className="block text-xs text-muted-foreground hover:text-foreground">외 {stats.length - 8}개 그룹 ›</Link>}
      </div>}
  </HomeBlock>
}

function DataLinks({ sector }: { sector: string }) {
  const links = sectorDataLinks(sector)
  if (!links.length) return null
  return <HomeBlock label="sector.data" title="이 산업의 데이터">
    <div className="grid gap-2 sm:grid-cols-3">
      {links.map(k => <Link key={k} to={SECTOR_DATA_LINKS[k].to} className="border px-3 py-3 text-sm font-semibold hover:bg-muted/50">{SECTOR_DATA_LINKS[k].label} ›</Link>)}
    </div>
  </HomeBlock>
}

function SectorPeerMap({ rows, peers, links }: { rows: SectorGroup[]; peers: Runtime; links: Links }) {
  const d = peers.data
  const entries = links.data?.sectors
  const entryOf = (sector: string): SectorPeerEntry | undefined => entries?.find(e => e.sector === sector)
  const groupsOf = (sector: string) => d && entries ? sectorPeerGroups(d.catalog, entryOf(sector)) : null
  const linkedCount = rows.filter(r => groupsOf(r.name)?.top.length).length
  const partialCount = rows.filter(r => { const s = groupsOf(r.name); return s?.top.length && s.partial }).length
  const ready = !!d && !!entries
  return <HomeBlock label="sector.map" title={<>섹터 → Peer 그룹 {ready && <span className="ml-1 text-xs font-normal text-muted-foreground">{rows.length}개 중 {linkedCount}개 연결 · 부분 {partialCount}</span>}</>}
    info={`섹터마다 이어진 Peer 그룹과 구성 종목 수, ${TABLE_DAYS}거래일 중앙값입니다. '부분'은 섹터의 일부 업종만 덮는 연결, '자동'은 연결이 없는 섹터에 구성 종목의 ${Math.round((links.data?.auto_share ?? 0.6) * 100)}% 이상이 그 섹터인 그룹을 붙인 것입니다.`} bodyClassName="p-0">
    {peers.isPending || links.isPending ? <div className="p-3"><RowsSkeleton rows={6} /></div>
      : !d ? <div className="p-3"><BlockError message="Peer 그룹을 불러오지 못했습니다" error={peers.error} onRetry={() => void peers.refetch()} /></div>
      : !entries ? <div className="p-3"><BlockError message="섹터 → Peer 대응표를 불러오지 못했습니다" error={links.error} onRetry={() => void links.refetch()} /></div>
      : <ul className="divide-y">{rows.map(r => {
        const entry = entryOf(r.name)
        const s = sectorPeerGroups(d.catalog, entry)
        const auto = !!entry?.links.length && entry.links.every(l => l.source === "auto")
        const children = s.top.reduce((n, id) => n + peerChildren(d.catalog, id).length, 0)
        return <li key={r.name} data-sector-peer={r.name} className="grid grid-cols-[9rem_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2.5 text-[13px]">
          <span className={cn("flex items-center gap-1.5", s.top.length ? "font-semibold" : "text-muted-foreground")}>{r.name}
            {s.partial && <Badge variant="secondary" className="h-4 px-1 text-[10px] font-normal">부분</Badge>}
            {auto && <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">자동</Badge>}</span>
          <span className="flex flex-wrap gap-1.5">{s.top.length ? s.top.map(id => {
            const codes = groupCodes(d.catalog, id)
            const ret = groupMedianReturn(d.prices, codes, TABLE_DAYS)
            return <Link key={id} to={`/discover/peers?group=${id}`} className="border px-2 py-0.5 text-xs hover:bg-muted/50">
              {d.catalog.groups.find(x => x.id === id)?.name ?? id} <span className="text-muted-foreground">{codes.length}사</span> <span className={cn("font-mono tabular-nums", tone(ret))}>{formatPercent(ret)}</span>
            </Link>
          }) : <span className="text-xs text-muted-foreground">연결된 Peer 그룹 없음</span>}</span>
          <span className="text-right text-xs text-muted-foreground">{s.top.length ? (children ? `사업군 ${children}` : s.note ?? "") : ""}</span>
        </li>
      })}</ul>}
  </HomeBlock>
}

/** 모바일 섹터 시트 — 장기 RS · 단기 RS 4주 흐름 · 5일, Peer 그룹 20일 중앙값 상위 3, 이동 칩 */
function SectorSheet({ g, peers, links }: { g: SectorGroup; peers: Runtime; links: Links }) {
  const d = peers.data
  const linked = d && links.data ? sectorPeerGroups(d.catalog, links.data.sectors.find(e => e.sector === g.name)) : null
  const top3 = d && linked ? groupStats(d.catalog, d.prices, linked.all).slice(0, 3) : []
  const chips = [
    ...(linked?.top.length ? [{ to: `/discover/peers?group=${linked.top[0]}`, label: "Peer 비교 열기" }] : []),
    ...sectorDataLinks(g.name).filter(k => k !== "usSeason").map(k => SECTOR_DATA_LINKS[k]),
  ]
  return <>
    <SheetHeader className="pb-0">
      <SheetTitle className="flex items-baseline gap-2">{g.name}<span className="text-xs font-normal text-muted-foreground">{formatNumber(g.stocks)}종목 · {formatKrw(g.market_cap)}</span></SheetTitle>
      <SheetDescription className="sr-only">섹터 상대강도와 Peer 그룹</SheetDescription>
    </SheetHeader>
    <div className="space-y-4 px-4 pb-6">
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div><p className="text-xs text-muted-foreground">장기 RS</p><p className="font-mono text-lg tabular-nums">{g.rs_long ?? "-"}</p></div>
        <div><p className="text-xs text-muted-foreground">단기 RS 4주</p><p className="font-mono tabular-nums">{shortRsTrail(g).map(t => t.value ?? "-").join(" → ")}</p></div>
        <div><p className="text-xs text-muted-foreground">5일</p><p className={cn("font-mono tabular-nums", tone(g.chg_5d))}>{formatPercent(g.chg_5d)}</p></div>
      </div>
      {peers.isPending || links.isPending ? <RowsSkeleton rows={3} head={false} />
        : peers.isError ? <BlockError message="Peer 그룹을 불러오지 못했습니다" error={peers.error} onRetry={() => void peers.refetch()} />
        : links.isError ? <BlockError message="섹터 → Peer 대응표를 불러오지 못했습니다" error={links.error} onRetry={() => void links.refetch()} />
        : !top3.length ? <p role="status" className="text-sm text-muted-foreground">이 업종엔 아직 Peer 그룹이 없습니다.</p>
        : <div>
          <ul className="divide-y border-y text-sm">{top3.map(s => <li key={s.id} className="flex items-center justify-between py-2">
            <span>{s.name} <span className="text-xs text-muted-foreground">{s.count}종목</span></span>
            <span className={cn("font-mono tabular-nums", tone(s.ret20))}>{formatPercent(s.ret20)}</span>
          </li>)}</ul>
          <p className="mt-1 text-xs text-muted-foreground">Peer 그룹 {TABLE_DAYS}일 중앙값</p>
        </div>}
      {chips.length > 0 && <div className="flex flex-wrap gap-2">{chips.map(c => <Button key={c.to} asChild variant="outline" size="sm" className="h-8 rounded-full text-xs"><Link to={c.to}>{c.label} ›</Link></Button>)}</div>}
    </div>
  </>
}
