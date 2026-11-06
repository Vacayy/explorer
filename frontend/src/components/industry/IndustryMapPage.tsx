import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Search } from "lucide-react"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { Band, FillNote, FillSkeleton, MarketCard, Seg } from "@/components/home/MarketFrame"
import { FillArea } from "@/components/shared/Bounded"
import { PageLayout } from "@/components/shared/PageLayout"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Chip, MiniLines, RS_INFO, benchmarkName, sectorPath } from "@/components/industry/sectorParts"
import { useIsMobile } from "@/hooks/use-mobile"
import { usePeerRuntime } from "@/hooks/usePeerRuntime"
import { useSectorPeers } from "@/hooks/useSectorMap"
import { useIndustryMap } from "@/hooks/useSectorView"
import { useUrlParam } from "@/hooks/useUrlParam"
import { sectorOfPeerGroup } from "@/lib/sectorPeers"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber, formatPercent } from "@/utils/format"
import type { IndustryMap, IndustryMapSector } from "@/types"

const RANK_SORTS = [{ key: "long", label: "장기 RS" }, { key: "r1m", label: "1개월" }, { key: "cap", label: "시총" }] as const
type RankSort = (typeof RANK_SORTS)[number]["key"]
const sortKey = (s: RankSort) => (g: IndustryMapSector) => s === "long" ? g.rs_long : s === "r1m" ? g.ret_1m : g.market_cap
const mmdd = (d: string | null | undefined) => d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : "-"
const WALL_INFO = "섹터마다 대표 ETF(예: 반도체 = KODEX 반도체 091160)를 대표지수로 씁니다. 대응 ETF가 없는 섹터는 Explorer 계산 지수(시총 가중)로 표시합니다. 1개월·3개월도 대표지수 기준입니다. 누르면 섹터 화면으로 갑니다."

/**
 * 산업 › 섹터 지도 (/industry, ia-redesign §4.35, 시안 Industry-Map, D-327).
 * ① 상대강도 지도 | 섹터 순위(460) — 지도는 '지도 | 표' 전환(URL v, 폰 기본 표), 순위 정렬 URL rank(장기 RS·1개월·시총).
 * ② 섹터 카드 벽(6열, 폰 2열) — 60거래일 대표지수(실선)·코스피(점선), 누르면 섹터 화면. 위 찾기(URL q)는 섹터·Peer 그룹·종목.
 * 원천 GET /api/spine/industry/map(저장분만). Peer 그룹 찾기는 Peer 게시본(/api/peers/runtime)과 섹터 대응표.
 */
export default function IndustryMapPage() {
  const map = useIndustryMap()
  const mobile = useIsMobile()
  const [hover, setHover] = useState<string | null>(null)
  const lead = useMemo(() => [...(map.data?.sectors ?? [])].sort((a, b) => (b.rs_long ?? -1) - (a.rs_long ?? -1))[0]?.name ?? null, [map.data])
  const focus = hover ?? lead
  return <PageLayout mode="document">
    <div className="flex flex-col gap-4">
      <Band label="상대강도" cells={[[7, <RsMapCard key="map" q={map} mobile={mobile} focus={focus} onHover={setHover} />], ...(mobile ? [] : [[5, <RankCard key="rank" q={map} focus={focus} onHover={setHover} />] as [number, React.ReactNode]])]} />
      <SectorWall q={map} focus={focus} onHover={setHover} />
    </div>
  </PageLayout>
}

type MapQuery = ReturnType<typeof useIndustryMap>

function RsMapCard({ q, mobile, focus, onHover }: { q: MapQuery; mobile: boolean; focus: string | null; onHover: (s: string | null) => void }) {
  const [v, setV] = useUrlParam("v", mobile ? "table" : "map")
  const d = q.data
  return <MarketCard band="sectorMap" label="industry.map">
    <BlockHead section title="상대강도 지도" info={`${RS_INFO} 점 크기는 시가총액, 점선은 고른 섹터의 지난 4주 이동 경로입니다.`}
      sub={d ? `${d.sectors.length}개 섹터 · ${mmdd(d.as_of)} · 점선 = 고른 섹터의 지난 4주` : " "}
      actions={<Seg label="보기" value={v} items={[{ key: "map", label: "지도" }, { key: "table", label: "표" }]} onChange={setV} />} />
    {q.isError ? <BlockError message="섹터 상대강도를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !d ? <FillSkeleton rows={10} />
      : !d.sectors.length ? <FillNote>주가·섹터 데이터가 쌓이면 나타납니다.</FillNote>
      : v === "map" ? <Scatter rows={d.sectors} focus={focus} onHover={onHover} />
      : <RankList rows={d.sectors} sort="long" focus={focus} onHover={onHover} wide={!mobile} />}
  </MarketCard>
}

/** 지도 — 가로 단기 RS, 세로 장기 RS, 점 크기 시총, 고른 섹터만 4주 경로(점선). 점·이름을 누르면 섹터 화면 */
function Scatter({ rows, focus, onHover }: { rows: IndustryMapSector[]; focus: string | null; onHover: (s: string | null) => void }) {
  const navigate = useNavigate()
  const W = 760, H = 380
  const X = (v: number) => 70 + v / 100 * (W - 100)
  const Y = (v: number) => H - 30 - v / 100 * (H - 70)
  const mx = Math.max(...rows.map(r => r.market_cap), 1)
  const quad: [string, number, number][] = [["주도", X(75), Y(92)], ["숨 고르기", X(8), Y(92)], ["반등 시도", X(75), Y(4)], ["소외", X(8), Y(4)]]
  const placed = rows.filter(r => r.rs_long != null && r.rs_short != null)
  const sel = placed.find(r => r.name === focus)
  const trail = sel ? [...sel.trail].sort((a, b) => b.weeks_ago - a.weeks_ago).filter(t => t.rs_long != null && t.rs_short != null).map(t => [t.rs_short!, t.rs_long!]).concat([[sel.rs_short!, sel.rs_long!]]) : []
  return <div className="min-h-0 flex-1">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="섹터 상대강도 지도" className="h-full w-full font-sans">
      <line x1={X(50)} x2={X(50)} y1={Y(100)} y2={Y(0)} className="stroke-line-2" strokeDasharray="3 4" />
      <line x1={X(0)} x2={X(100)} y1={Y(50)} y2={Y(50)} className="stroke-line-2" strokeDasharray="3 4" />
      {quad.map(([t, x, y]) => <text key={t} x={x} y={y} fontSize="12" className="fill-ink-3">{t}</text>)}
      {trail.length > 1 && <polyline points={trail.map(([a, b]) => `${X(a).toFixed(1)},${Y(b).toFixed(1)}`).join(" ")} fill="none" className="stroke-up" strokeWidth="1.6" strokeDasharray="4 3" />}
      {placed.map(r => {
        const on = r.name === focus
        const rad = 4 + Math.sqrt(r.market_cap / mx) * 12
        const left = r.rs_short! > 80
        return <g key={r.name} role="link" tabIndex={0} aria-label={`${r.name} 장기 RS ${r.rs_long} 단기 RS ${r.rs_short}`} className="cursor-pointer outline-none"
          onMouseEnter={() => onHover(r.name)} onMouseLeave={() => onHover(null)} onFocus={() => onHover(r.name)} onBlur={() => onHover(null)}
          onClick={() => navigate(sectorPath(r.name))} onKeyDown={e => { if (e.key === "Enter") navigate(sectorPath(r.name)) }}>
          <circle cx={X(r.rs_short!)} cy={Y(r.rs_long!)} r={rad} className={cn(on ? "fill-up" : "fill-ink-2", "stroke-surface")} fillOpacity={on ? 0.9 : 0.28} strokeWidth="2" />
          <text x={X(r.rs_short!) + (left ? -(rad + 4) : rad + 4)} y={Y(r.rs_long!) + 4} textAnchor={left ? "end" : "start"} fontSize={on ? 12 : 11} fontWeight={on ? 600 : 400} className={on ? "fill-ink" : "fill-ink-2"}>{r.name}</text>
        </g>
      })}
      <text x={X(100)} y={H - 8} textAnchor="end" fontSize="11" className="fill-ink-3">단기 RS →</text>
      <text x="4" y={Y(100) - 14} fontSize="11" className="fill-ink-3">장기 RS ↑</text>
    </svg>
  </div>
}

function RankCard({ q, focus, onHover }: { q: MapQuery; focus: string | null; onHover: (s: string | null) => void }) {
  const [sort, setSort] = useUrlParam("rank", "long")
  const s = (RANK_SORTS.find(x => x.key === sort)?.key ?? "long") as RankSort
  return <MarketCard band="sectorMap" label="industry.rank">
    <BlockHead section title="섹터 순위" sub={`${RANK_SORTS.find(x => x.key === s)!.label} 순`}
      actions={<Seg label="정렬" value={s} items={RANK_SORTS.map(x => ({ key: x.key, label: x.label }))} onChange={setSort} />} />
    {q.isError ? <BlockError message="섹터 순위를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !q.data ? <FillSkeleton rows={10} />
      : !q.data.sectors.length ? <FillNote>주가·섹터 데이터가 쌓이면 나타납니다.</FillNote>
      : <RankList rows={q.data.sectors} sort={s} focus={focus} onHover={onHover} />}
  </MarketCard>
}

const RANK_COLS = "grid-cols-[minmax(0,1fr)_54px_46px_46px_54px]"
const WIDE_COLS = "grid-cols-[minmax(0,1fr)_64px_54px_54px_46px_46px_54px]"

/** 순위 줄 — 섹터 · 1개월 · 장기 · 단기 · 5일 (넓은 표 보기는 시총·3개월을 더한다). 줄을 누르면 섹터 화면 */
function RankList({ rows, sort, focus, onHover, wide }: { rows: IndustryMapSector[]; sort: RankSort; focus: string | null; onHover: (s: string | null) => void; wide?: boolean }) {
  const key = sortKey(sort)
  const sorted = [...rows].sort((a, b) => (key(b) ?? -Infinity) - (key(a) ?? -Infinity))
  const cols = wide ? WIDE_COLS : RANK_COLS
  return <>
    <div className={cn("grid shrink-0 gap-2 text-[11.5px] text-ink-3", cols)}>
      <span>섹터</span>{wide && <span className="text-right">시총</span>}<span className="text-right">1개월</span>{wide && <span className="text-right">3개월</span>}<span className="text-right">장기</span><span className="text-right">단기</span><span className="text-right">5일</span>
    </div>
    <FillArea aria-label="섹터 순위">
      {sorted.map(r => <Link key={r.name} to={sectorPath(r.name)} data-sector-row onMouseEnter={() => onHover(r.name)} onMouseLeave={() => onHover(null)}
        className={cn("grid items-center gap-2 border-b py-2 text-[12.5px]", cols, r.name === focus && "bg-up-tint")}>
        <span className={cn("truncate", r.name === focus && "font-semibold")}>{r.name}</span>
        {wide && <span className="text-right font-mono text-ink-2 tabular-nums">{formatKrw(r.market_cap)}</span>}
        <span className={cn("text-right font-mono tabular-nums", tone(r.ret_1m))}>{formatPercent(r.ret_1m)}</span>
        {wide && <span className={cn("text-right font-mono tabular-nums", tone(r.ret_3m))}>{formatPercent(r.ret_3m)}</span>}
        <span className="text-right font-mono tabular-nums">{r.rs_long == null ? "-" : Math.round(r.rs_long)}</span>
        <span className="text-right font-mono tabular-nums">{r.rs_short == null ? "-" : Math.round(r.rs_short)}</span>
        <span className={cn("text-right font-mono tabular-nums", tone(r.chg_5d))}>{formatPercent(r.chg_5d)}</span>
      </Link>)}
    </FillArea>
  </>
}

/** ② 섹터 카드 벽 + 찾기(섹터·Peer 그룹·종목) + 섹터 밖 그룹 */
function SectorWall({ q, focus, onHover }: { q: MapQuery; focus: string | null; onHover: (s: string | null) => void }) {
  const [query, setQuery] = useUrlParam("q", "")
  const d = q.data
  const term = query.trim()
  const cards = useMemo(() => [...(d?.sectors ?? [])].sort((a, b) => b.market_cap - a.market_cap)
    .filter(r => !term || r.name.includes(term) || (r.benchmark.name ?? "").includes(term)), [d, term])
  return <section aria-label="섹터" className="flex flex-col gap-3 rounded-[var(--radius-card)] border bg-card px-[18px] py-4">
    <BlockHead section title="섹터" info={WALL_INFO} sub="시총 순 · 선 = 60거래일 대표지수, 점선 = 코스피"
      actions={<label className="relative flex h-8 w-[260px] items-center max-sm:w-full">
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 size-3.5 text-ink-3" />
        <Input type="search" aria-label="섹터·Peer 그룹·종목 찾기" value={query} onChange={e => setQuery(e.target.value)} placeholder="섹터·Peer 그룹·종목 찾기"
          className="h-8 rounded-full border-0 bg-chip pl-8 text-[12.5px] shadow-none" />
      </label>} />
    {term && d && <FindResults term={term} map={d} />}
    {q.isError ? <BlockError message="섹터를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !d ? <div className="grid grid-cols-2 pr-px pb-px md:grid-cols-6 [&>*]:-mr-px [&>*]:-mb-px">{Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="h-[176px] rounded-none border" />)}</div>
      : !cards.length ? (term ? null : <FillNote>주가·섹터 데이터가 쌓이면 나타납니다.</FillNote>)
      : <div className="grid grid-cols-2 pr-px pb-px md:grid-cols-3 lg:grid-cols-6 [&>*]:-mr-px [&>*]:-mb-px">
        {cards.map(r => <SectorCard key={r.name} r={r} kospi={d.kospi} on={r.name === focus} onHover={onHover} />)}
      </div>}
    {d && d.outside_groups.length > 0 && <div className="flex flex-col gap-2 border-t pt-3">
      <h3 className="text-[13px] font-semibold">섹터 밖 그룹 <span className="font-normal text-ink-3">{d.outside_groups.length}</span></h3>
      <div className="flex flex-wrap gap-1.5">{d.outside_groups.map(g => <Link key={g.id} to={`/industry?q=${encodeURIComponent(g.name)}`}><Chip>{g.name} · {g.members}사</Chip></Link>)}</div>
    </div>}
  </section>
}

function SectorCard({ r, kospi, on, onHover }: { r: IndustryMapSector; kospi: number[]; on: boolean; onHover: (s: string | null) => void }) {
  const strong = (r.rs_long ?? 0) >= 70
  return <Link to={sectorPath(r.name)} onMouseEnter={() => onHover(r.name)} onMouseLeave={() => onHover(null)} aria-label={`${r.name} 섹터 화면`}
    className={cn("flex h-[176px] min-w-0 flex-col gap-[5px] border bg-card p-3 hover:bg-surface-2", on && "relative z-[1] border-ink")}>
    <div className="flex min-w-0 items-center gap-1.5">
      <span className="truncate text-[13.5px] font-semibold">{r.name}</span>
      <Chip kind={strong ? "up" : "chip"} className="ml-auto">RS {r.rs_long == null ? "-" : Math.round(r.rs_long)}·{r.rs_short == null ? "-" : Math.round(r.rs_short)}</Chip>
    </div>
    <div className="flex min-w-0 items-baseline gap-2">
      <span className={cn("font-mono text-[15px] tabular-nums", tone(r.ret_1m))}>{formatPercent(r.ret_1m)}</span>
      <span className="truncate text-[11.5px] text-ink-3">1개월 · 3개월 {formatPercent(r.ret_3m, 0)}</span>
    </div>
    <MiniLines series={r.series} kospi={kospi.slice(-r.series.length)} accent={on} />
    <span className="truncate text-[11.5px] text-ink-3" title={benchmarkName(r.benchmark)}>{formatNumber(r.stocks)}종목 · 시총 {formatKrw(r.market_cap)}{r.peer_groups != null && ` · Peer ${r.peer_groups}`}</span>
  </Link>
}

/** 찾기 결과 — 섹터 이름은 카드 벽을 거르고, Peer 그룹·종목(Peer 카탈로그)은 그 섹터 화면 Peer 탭으로 */
function FindResults({ term, map }: { term: string; map: IndustryMap }) {
  const runtime = usePeerRuntime()
  const links = useSectorPeers()
  const catalog = runtime.data?.catalog
  const found = useMemo(() => {
    if (!catalog || !links.data) return null
    const t = term.toLowerCase()
    const groups = catalog.groups.filter(g => g.name.toLowerCase().includes(t)).slice(0, 12)
    const companies = catalog.companies.filter(c => c.name.toLowerCase().includes(t) || c.code === term || c.aliases.some(a => a.toLowerCase().includes(t))).slice(0, 8)
    const to = (gid: string, stock?: string) => {
      const sector = sectorOfPeerGroup(catalog, links.data.sectors, gid)
      return sector ? sectorPath(sector, `?tab=peers&group=${encodeURIComponent(gid)}${stock ? `&stock=${stock}` : ""}`) : null
    }
    return { groups: groups.map(g => ({ g, to: to(g.id) })), companies: companies.map(c => ({ c, to: c.groupIds[0] ? to(c.groupIds[0], c.code) : null })) }
  }, [catalog, links.data, term])
  if (!found) return runtime.isError || links.isError ? null : <Skeleton className="h-8 w-full" />
  const outside = map.outside_groups.filter(g => g.name.includes(term))
  if (!found.groups.length && !found.companies.length && !outside.length) return <p role="status" className="text-[13px] text-ink-3">"{term}"이 들어간 Peer 그룹·종목이 없습니다.</p>
  return <div className="flex flex-col gap-2 text-[13px]" aria-label="찾기 결과">
    {found.groups.length > 0 && <div className="flex flex-wrap items-center gap-1.5"><span className="w-14 shrink-0 text-[12px] text-ink-3">Peer 그룹</span>
      {found.groups.map(({ g, to }) => to ? <Link key={g.id} to={to}><Chip>{g.name}</Chip></Link> : <Link key={g.id} to={`/industry?q=${encodeURIComponent(g.name)}`}><Chip kind="warn">{g.name} · 섹터 밖</Chip></Link>)}
    </div>}
    {found.companies.length > 0 && <div className="flex flex-wrap items-center gap-1.5"><span className="w-14 shrink-0 text-[12px] text-ink-3">종목</span>
      {found.companies.map(({ c, to }) => <Link key={c.code} to={to ?? `/analyze/${c.code}/summary`}><Chip>{c.name}</Chip></Link>)}
    </div>}
  </div>
}
