import { useMemo, useState } from "react"
import { PUBLIC_ACCESS } from "@/lib/accessMode"
import { Link, useNavigate } from "react-router-dom"
import { Search } from "lucide-react"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { Band, FillNote, FillSkeleton, MarketCard, Seg } from "@/components/home/MarketFrame"
import { FillArea } from "@/components/shared/Bounded"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Chip, MiniLines, US_RS_INFO, usSectorPath } from "@/components/industry/sectorParts"
import { useIsMobile } from "@/hooks/use-mobile"
import { useUsIndustryMap } from "@/hooks/useSectorView"
import { useUrlParam } from "@/hooks/useUrlParam"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { UsMapSector } from "@/types"

const RANK_SORTS = [{ key: "long", label: "장기 RS" }, { key: "r1m", label: "1개월" }, { key: "cov", label: "내 커버리지" }] as const
type RankSort = (typeof RANK_SORTS)[number]["key"]
const sortKey = (s: RankSort) => (g: UsMapSector) => s === "long" ? g.rs_long : s === "r1m" ? g.ret_1m : g.coverage
const FILTERS = [{ key: "all", label: "전체" }, { key: "gics", label: "GICS 11" }, { key: "sub", label: "세부 업종" }] as const
const mmdd = (d: string | null | undefined) => d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : "-"
const WALL_INFO = "섹터마다 대표 ETF(GICS = SPDR 섹터 ETF, 세부 업종 = 업종 ETF)를 대표지수로 씁니다. '내 커버리지'는 팔로우 종목 중 그 섹터·업종(Yahoo 분류)에 속한 수입니다. 누르면 섹터 화면으로 갑니다."
const rsText = (v: number | null) => v == null ? "-" : String(Math.round(v))

type Q = ReturnType<typeof useUsIndustryMap>

/**
 * 산업 › 섹터 지도 · 미국 (/industry?market=us, ia-redesign §4.36, 시안 Industry-Map-US).
 * 지도·순위·카드 = 섹터 ETF(GICS 11 + 세부 업종 13, 비교 SPY), 섹터 안 종목 = 내 커버리지.
 * ① 상대강도 지도(채운 점 GICS · 빈 점 세부 업종, 거르기 URL uf) | 섹터 순위(↳ 세부 업종, 정렬 URL rank) — 480 고정
 * ② 카드 벽(GICS 순, 세부 업종은 상위 뒤, 찾기 URL q) — 60거래일 ETF(실선)·SPY(점선), 누르면 미국 섹터 화면.
 */
export default function UsIndustryMap({ bar }: { bar: (asOf: string | null | undefined) => React.ReactNode }) {
  const q = useUsIndustryMap()
  const mobile = useIsMobile()
  const [hover, setHover] = useState<string | null>(null)
  const lead = useMemo(() => [...(q.data?.sectors ?? [])].sort((a, b) => (b.rs_long ?? -1) - (a.rs_long ?? -1))[0]?.ticker ?? null, [q.data])
  const focus = hover ?? lead
  return <div className="flex flex-col gap-4">
    {bar(q.data?.as_of)}
    {/* 폰은 지도 대신 순위만(국내 지도의 폰 기본 '표'와 같은 판단 — 24개 라벨이 390 폭에 겹친다) */}
    <Band label="상대강도" cells={mobile ? [[12, <RankCard key="rank" q={q} focus={focus} onHover={setHover} />]]
      : [[7, <RsMapCard key="map" q={q} focus={focus} onHover={setHover} />], [5, <RankCard key="rank" q={q} focus={focus} onHover={setHover} />]]} />
    <Wall q={q} focus={focus} onHover={setHover} mobile={mobile} />
  </div>
}

function RsMapCard({ q, focus, onHover }: { q: Q; focus: string | null; onHover: (s: string | null) => void }) {
  const [f, setF] = useUrlParam("uf", "all")
  const d = q.data
  const rows = (d?.sectors ?? []).filter(r => f === "all" || (f === "gics" ? r.parent == null : r.parent != null))
  return <MarketCard band="usSectorMap" label="industry.us.map">
    <BlockHead section title="상대강도 지도" info={`${US_RS_INFO} 채운 점은 GICS 섹터, 빈 점은 세부 업종입니다. 점선은 고른 섹터·업종의 지난 4주 이동 경로입니다.`}
      sub={d ? `${d.sectors.length}개 섹터·업종 · ${mmdd(d.as_of)}` : " "}
      actions={<Seg label="거르기" value={f} items={FILTERS.map(x => ({ key: x.key, label: x.label }))} onChange={setF} />} />
    <div className="flex shrink-0 gap-3.5 text-[11.5px] text-ink-3" aria-hidden>
      <span className="inline-flex items-center gap-[5px]"><span className="size-2.5 rounded-full bg-ink-2 opacity-45" />GICS 섹터 11</span>
      <span className="inline-flex items-center gap-[5px]"><span className="size-2 rounded-full border-[1.4px] border-ink-2" />세부 업종 13</span>
    </div>
    {q.isError ? <BlockError message="미국 섹터 상대강도를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !d ? <FillSkeleton rows={10} />
      : !d.sectors.length ? <FillNote>섹터 ETF 시세가 쌓이면 나타납니다.</FillNote>
      : <Scatter rows={rows} focus={focus} onHover={onHover} />}
  </MarketCard>
}

/** 지도 — 가로 단기 RS, 세로 장기 RS. 채운 점 = GICS, 빈 점 = 세부 업종(점 크기는 쓰지 않는다 — ETF 시총은 섹터 크기가 아니다) */
function Scatter({ rows, focus, onHover }: { rows: UsMapSector[]; focus: string | null; onHover: (s: string | null) => void }) {
  const navigate = useNavigate()
  const W = 760, H = 400
  const X = (v: number) => 70 + v / 100 * (W - 120)
  const Y = (v: number) => H - 44 - v / 100 * (H - 104)
  const quad: [string, number, number][] = [["주도", X(75), 22], ["숨 고르기", X(25), 22], ["반등 시도", X(75), H - 8], ["소외", X(25), H - 8]]
  const placed = rows.filter(r => r.rs_long != null && r.rs_short != null).sort((a, b) => Number(a.ticker === focus) - Number(b.ticker === focus))
  const sel = placed.find(r => r.ticker === focus)
  const trail = sel ? [...sel.trail].sort((a, b) => b.weeks_ago - a.weeks_ago).filter(t => t.rs_long != null && t.rs_short != null).map(t => [t.rs_short!, t.rs_long!]).concat([[sel.rs_short!, sel.rs_long!]]) : []
  return <div className="min-h-0 flex-1">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="미국 섹터 상대강도 지도" className="h-full w-full font-sans">
      <line x1={X(50)} x2={X(50)} y1={Y(100)} y2={Y(0)} className="stroke-line-2" strokeDasharray="3 4" />
      <line x1={X(0)} x2={X(100)} y1={Y(50)} y2={Y(50)} className="stroke-line-2" strokeDasharray="3 4" />
      {quad.map(([t, x, y]) => <text key={t} x={x} y={y} fontSize="12" textAnchor="middle" className="fill-ink-3">{t}</text>)}
      {trail.length > 1 && <polyline points={trail.map(([a, b]) => `${X(a).toFixed(1)},${Y(b).toFixed(1)}`).join(" ")} fill="none" className="stroke-up" strokeWidth="1.6" strokeDasharray="4 3" />}
      {placed.map(r => {
        const on = r.ticker === focus
        const sub = r.parent != null
        const x = X(r.rs_short!), y = Y(r.rs_long!)
        const left = r.rs_short! > 78
        const go = () => navigate(usSectorPath(r.ticker))
        return <g key={r.ticker} role="link" tabIndex={0} aria-label={`${r.name}(${r.ticker}) 장기 RS ${rsText(r.rs_long)} 단기 RS ${rsText(r.rs_short)}`} className="cursor-pointer outline-none"
          onMouseEnter={() => onHover(r.ticker)} onMouseLeave={() => onHover(null)} onFocus={() => onHover(r.ticker)} onBlur={() => onHover(null)}
          onClick={go} onKeyDown={e => { if (e.key === "Enter") go() }}>
          {sub && !on ? <circle cx={x} cy={y} r={5} className="fill-surface stroke-ink-2" strokeWidth="1.4" />
            : <circle cx={x} cy={y} r={sub ? 6 : 7} className={cn(on ? "fill-up" : "fill-ink-2", "stroke-surface")} fillOpacity={on ? 0.9 : 0.35} strokeWidth="2" />}
          <text x={x + (left ? -10 : 10)} y={y + 4} textAnchor={left ? "end" : "start"} fontSize={on ? 12 : 11} fontWeight={on ? 600 : 400}
            paintOrder="stroke" strokeWidth="4" strokeLinejoin="round" className={cn("stroke-surface", on ? "fill-ink" : sub ? "fill-ink-3" : "fill-ink-2")}>{r.name}</text>
        </g>
      })}
      <text x={X(100)} y={H - 8} textAnchor="end" fontSize="11" className="fill-ink-3">단기 RS(1주) →</text>
      <text x="4" y={Y(100) - 14} fontSize="11" className="fill-ink-3">장기 RS(3개월) ↑</text>
    </svg>
  </div>
}

const RANK_COLS = "grid-cols-[minmax(0,1fr)_44px_54px_40px_40px_54px]"

function RankCard({ q, focus, onHover }: { q: Q; focus: string | null; onHover: (s: string | null) => void }) {
  const [sort, setSort] = useUrlParam("rank", "long")
  const sorts = RANK_SORTS.filter(x => !PUBLIC_ACCESS || x.key !== "cov")
  const s = (sorts.find(x => x.key === sort)?.key ?? "long") as RankSort
  const key = sortKey(s)
  const rows = [...(q.data?.sectors ?? [])].sort((a, b) => (key(b) ?? -Infinity) - (key(a) ?? -Infinity))
  return <MarketCard band="usSectorMap" label="industry.us.rank">
    <BlockHead section title="섹터 순위" sub={`${RANK_SORTS.find(x => x.key === s)!.label} 순 · ↳ 세부 업종`}
      actions={<Seg label="정렬" value={s} items={sorts.map(x => ({ key: x.key, label: x.label }))} onChange={setSort} />} />
    <div className={cn("grid shrink-0 gap-2 text-[11.5px] text-ink-3", RANK_COLS)}>
      <span>섹터·업종</span><span>ETF</span><span className="text-right">1개월</span><span className="text-right">장기</span><span className="text-right">단기</span><span className="text-right">1주</span>
    </div>
    {q.isError ? <BlockError message="미국 섹터 순위를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !q.data ? <FillSkeleton rows={10} />
      : !rows.length ? <FillNote>섹터 ETF 시세가 쌓이면 나타납니다.</FillNote>
      : <FillArea aria-label="섹터 순위">
        {rows.map(r => <Link key={r.ticker} to={usSectorPath(r.ticker)} data-sector-row onMouseEnter={() => onHover(r.ticker)} onMouseLeave={() => onHover(null)}
          className={cn("grid items-center gap-2 border-b py-2 text-[12.5px]", RANK_COLS, r.ticker === focus && "bg-up-tint")}>
          <span className={cn("truncate", r.ticker === focus && "font-semibold")}>{r.parent && <span className="text-ink-3">↳ </span>}{r.name}</span>
          <span className="font-mono text-[11.5px] text-ink-3">{r.ticker}</span>
          <span className={cn("text-right font-mono tabular-nums", tone(r.ret_1m))}>{formatPercent(r.ret_1m)}</span>
          <span className="text-right font-mono tabular-nums">{rsText(r.rs_long)}</span>
          <span className="text-right font-mono tabular-nums">{rsText(r.rs_short)}</span>
          <span className={cn("text-right font-mono tabular-nums", tone(r.chg_1w))}>{formatPercent(r.chg_1w)}</span>
        </Link>)}
      </FillArea>}
  </MarketCard>
}

/** ② 카드 벽 — 서버가 준 순서(GICS 순, 세부 업종은 상위 뒤) 그대로. 찾기는 이름·티커·ETF 정식 이름 */
function Wall({ q, focus, onHover, mobile }: { q: Q; focus: string | null; onHover: (s: string | null) => void; mobile: boolean }) {
  const [query, setQuery] = useUrlParam("q", "")
  const d = q.data
  const term = query.trim().toLowerCase()
  const names = useMemo(() => Object.fromEntries((d?.sectors ?? []).map(r => [r.ticker, r.name])), [d])
  const cards = (d?.sectors ?? []).filter(r => !term || r.name.toLowerCase().includes(term) || r.ticker.toLowerCase().includes(term) || r.full_name.toLowerCase().includes(term))
  return <section aria-label="섹터" className="flex flex-col gap-3 rounded-[var(--radius-card)] border bg-card px-[18px] py-4">
    <BlockHead section title="섹터" info={PUBLIC_ACCESS ? "섹터·업종 ETF의 가격과 상대강도를 비교합니다. 실선은 ETF, 점선은 S&P500(SPY)입니다." : WALL_INFO} sub={mobile ? "GICS 순 · 점선 = SPY" : "GICS 순, 세부 업종은 상위 섹터 뒤 · 선 = 60거래일 ETF, 점선 = S&P500(SPY)"}
      actions={<label className="relative flex h-8 w-[240px] items-center max-sm:w-full">
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 size-3.5 text-ink-3" />
        <Input type="search" aria-label="섹터·업종·티커 찾기" value={query} onChange={e => setQuery(e.target.value)} placeholder="섹터·업종·티커 찾기"
          className="h-8 rounded-full border-0 bg-chip pl-8 text-[12.5px] shadow-none" />
      </label>} />
    {q.isError ? <BlockError message="미국 섹터를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !d ? <div className="grid grid-cols-2 pr-px pb-px md:grid-cols-6 [&>*]:-mr-px [&>*]:-mb-px">{Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="h-[176px] rounded-none border" />)}</div>
      : !cards.length ? <p role="status" className="text-[13px] text-ink-3">{term ? `"${query.trim()}"에 맞는 섹터·업종이 없습니다.` : "섹터 ETF 시세가 쌓이면 나타납니다."}</p>
      : <div className="grid grid-cols-2 pr-px pb-px md:grid-cols-3 lg:grid-cols-6 [&>*]:-mr-px [&>*]:-mb-px">
        {cards.map(r => <Card key={r.ticker} r={r} spy={d.spy} parentName={r.parent ? names[r.parent] : null} on={r.ticker === focus} onHover={onHover} />)}
      </div>}
  </section>
}

function Card({ r, spy, parentName, on, onHover }: { r: UsMapSector; spy: number[]; parentName: string | null; on: boolean; onHover: (s: string | null) => void }) {
  return <Link to={usSectorPath(r.ticker)} onMouseEnter={() => onHover(r.ticker)} onMouseLeave={() => onHover(null)} aria-label={`${r.name}(${r.ticker}) 섹터 화면`}
    className={cn("flex h-[176px] min-w-0 flex-col gap-[5px] border p-3 hover:bg-surface-2", r.parent ? "bg-bg" : "bg-card", on && "relative z-[1] border-ink")}>
    <div className="flex min-w-0 items-center gap-1.5">
      <span className="truncate text-[13.5px] font-semibold">{parentName && <span className="text-xs font-normal text-ink-3">{parentName} › </span>}{r.name}</span>
      <Chip kind={(r.rs_long ?? 0) >= 70 ? "up" : "chip"} className="ml-auto">RS {rsText(r.rs_long)}·{rsText(r.rs_short)}</Chip>
    </div>
    <div className="flex min-w-0 items-baseline gap-2">
      <span className={cn("font-mono text-[15px] tabular-nums", tone(r.ret_1m))}>{formatPercent(r.ret_1m)}</span>
      <span className="truncate text-[11.5px] text-ink-3">1개월 · 3개월 {formatPercent(r.ret_3m, 0)}</span>
    </div>
    <MiniLines series={r.series} kospi={spy.slice(-r.series.length)} accent={on} />
    <span className="truncate text-[11.5px] text-ink-3" title={r.full_name}><span className="font-mono">{r.ticker}</span>{!PUBLIC_ACCESS && r.coverage != null && <> · 내 커버리지 {r.coverage}종목</>}</span>
  </Link>
}
