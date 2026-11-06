import type { ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { IndexLineChart, type IndexLinePoint } from "@/components/charts/IndexLineChart"
import { InfoTip } from "@/components/shared/InfoTip"
import { BAND } from "@/components/shared/Bounded"
import { Band, MarketCard, Seg } from "@/components/home/MarketFrame"
import { BlockError, tone } from "@/components/home/blockState"
import { useMarketOverview } from "@/hooks/useMarketOverview"
import { fearGreedZone } from "@/lib/macroPage"
import { cn } from "@/lib/utils"
import { formatKrw, formatLevel, formatLevelChange, formatNumber, formatPercent, formatYield } from "@/utils/format"
import type { IndexOverview, IndexRangeKey, MarketKey, OverviewTile } from "@/types"
import { track } from "@/lib/usage"

const RANGES: { key: IndexRangeKey; label: string }[] = [{ key: "1d", label: "1일" }, { key: "1m", label: "1개월" }, { key: "3m", label: "3개월" }, { key: "1y", label: "1년" }]
const WD = ["일", "월", "화", "수", "목", "금", "토"]
const md = (d: string) => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`
const mdw = (d: string) => `${md(d)}(${WD[new Date(`${d}T12:00:00Z`).getUTCDay()]})`
const mins = (hm: string) => +hm.slice(0, 2) * 60 + +hm.slice(3, 5)

/** 머리 회색 줄 — '11/5(목) 15:30 마감' · 미국은 '현지 16:00 마감 · 한국 11/6 06:00' */
function sessionMeta(i: IndexOverview, market: MarketKey): string {
  const s = i.session
  if (!s.trade_date) return "기록 없음"
  const when = s.state === "open" ? `${s.last_time ?? ""} 기준` : `${s.last_time ?? s.close} 마감`
  const local = `${mdw(s.trade_date)} ${market === "us" ? "현지 " : ""}${when}`
  const kst = market === "us" && s.last_kst ? ` · 한국 ${md(s.last_kst.slice(0, 10))} ${s.last_kst.slice(11)}` : ""
  return `${s.state === "pre" ? "개장 전 · " : ""}${local}${kst}`
}

/** 고른 기간의 점·눈금·기준선 — 1일은 개장~마감 시각 비율, 기간은 순번 비율 */
function rangeView(i: IndexOverview, key: IndexRangeKey) {
  const r = i.ranges.find(x => x.key === key)
  if (!r || !r.points.length) return null
  const last = r.points[r.points.length - 1].v
  if (key === "1d") {
    const o = mins(i.session.open), c = mins(i.session.close)
    const xs = (t: string) => Math.min(1, Math.max(0, (mins(t) - o) / (c - o)))
    const points: IndexLinePoint[] = r.points.map(p => ({ x: xs(p.t), v: p.v }))
    const ticks = (i.session.open === "09:00" ? ["09:00", "11:00", "13:00", "15:30"] : ["09:30", "11:30", "13:30", "16:00"]).map(t => ({ x: xs(t), t }))
    return { points, ticks, base: r.base, last, basis: "전일 대비" }
  }
  const n = r.points.length
  const at = (k: number) => n > 1 ? k / (n - 1) : 0.5
  const fmt = (d: string) => key === "1y" ? `${d.slice(2, 4)}.${d.slice(5, 7)}` : md(d)
  const idx = [...new Set([0, Math.floor(n / 3), Math.floor(2 * n / 3), n - 1])]
  return { points: r.points.map((p, k) => ({ x: at(k), v: p.v })), ticks: idx.map(k => ({ x: at(k), t: fmt(r.points[k].t) })), base: r.base, last,
    basis: RANGES.find(x => x.key === key)!.label }
}

/**
 * ① 지수 — 지수 차트(8/12) | 요약 지표 2×2(4/12). 원천 GET /api/spine/market/{kr|us}/overview(저장분만).
 * URL ?idx=(지수 키)&range=1d|1m|3m|1y. 좁은 화면은 차트 220 → 지표 2×2.
 */
export function MarketHero({ market }: { market: MarketKey }) {
  const q = useMarketOverview(market)
  const d = q.data
  const [params, setParams] = useSearchParams()
  const set = (k: string, v: string, dflt: string) => setParams(prev => {
    const n = new URLSearchParams(prev)
    if (v === dflt) n.delete(k); else n.set(k, v)
    return n
  }, { replace: true, preventScrollReset: true })
  const first = d?.indices[0]?.key ?? (market === "kr" ? "kospi" : "sp500")
  const idx = d?.indices.find(i => i.key === params.get("idx")) ?? d?.indices[0]
  const range = (RANGES.find(r => r.key === params.get("range"))?.key ?? "1d") as IndexRangeKey
  const view = idx ? rangeView(idx, range) : null
  const chg = view && view.base != null ? view.last - view.base : null
  const chgPct = view && view.base ? (view.last / view.base - 1) * 100 : null

  const hero = <MarketCard band="index" label={`${market}.index`} className="max-md:h-auto">
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
      <Seg label="지수" value={idx?.key ?? first} onChange={v => { track("action", "index.switch", { entity: `${v}:${range}` }); set("idx", v, first) }}
        items={(d?.indices ?? []).map(i => ({ key: i.key, label: i.name }))} />
      <Seg label="기간" value={range} onChange={v => { track("action", "index.switch", { entity: `${idx?.key ?? first}:${v}` }); set("range", v, "1d") }} items={RANGES} />
    </div>
    {!d ? (q.isError ? <BlockError message="지수를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
        : <div role="status" aria-label="지수 불러오는 중" className="flex min-h-0 flex-1 flex-col gap-3"><Skeleton className="h-11 w-72" /><Skeleton className="min-h-[220px] w-full flex-1" /></div>)
      : <>
        <div className="flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-display text-[40px] leading-[1.1] font-normal tracking-[-0.02em] tabular-nums max-sm:text-[32px]">{formatLevel(view?.last ?? idx?.value)}</span>
          <span className={cn("font-mono text-[15px] tabular-nums", tone(chg))}>{formatLevelChange(chg)} {formatPercent(chgPct, 2)}</span>
          <span className="text-xs text-ink-3">{view?.basis ?? "전일 대비"} · {idx ? sessionMeta(idx, market) : "-"}</span>
        </div>
        {view ? <IndexLineChart points={view.points} base={view.base} ticks={view.ticks} dim={range === "1d" && idx?.session.state === "pre"}
            label={`${idx?.name} ${view.basis} 추이`} className="min-h-0 flex-1 max-md:h-[220px] max-md:flex-none" />
          : <p role="status" className="flex min-h-0 flex-1 items-center text-sm text-ink-3 max-md:h-[220px] max-md:flex-none">{range === "1d" ? "장중 경로가 아직 없습니다." : "이 기간의 일별 종가가 없습니다."}</p>}
      </>}
  </MarketCard>

  const tiles = <div data-home-section={`${market}.tiles`} className={cn("grid grid-cols-2 grid-rows-2 pr-px pb-px [&>*]:-mr-px [&>*]:-mb-px", BAND.index)}>
    {d ? d.tiles.map(t => <Tile key={t.key} t={t} />)
      : [0, 1, 2, 3].map(i => <Card key={i} className="gap-2 rounded-[var(--radius-card)] px-4 py-3.5 shadow-none"><Skeleton className="h-3 w-16" /><Skeleton className="h-7 w-24" /><Skeleton className="h-3 w-28" /></Card>)}
  </div>

  return <Band label="지수" cells={[[8, hero], [4, tiles]]} />
}

/* ── 요약 지표 칸 ── */
const TIPS: Partial<Record<OverviewTile["key"], string>> = {
  breadth: "코스피·코스닥 전 종목의 전일 종가 대비 상승·하락 수(저장된 일별 시세)",
  indiv_net: "유가증권+코스닥 개인 매수 거래대금 − 매도 거래대금(한국거래소)",
  credit: "신용거래융자 전체(금융투자협회). 다음 영업일에 들어옵니다. 백분위는 20일 변화율을 지난 5년과 비교합니다",
  fear_greed: "CNN 공포·탐욕 지수 0~100. 25 아래 극단적 공포, 75 위 극단적 탐욕",
}

function Tile({ t }: { t: OverviewTile }) {
  const day = t.as_of ? md(t.as_of) : "-"
  const pct = <span className={tone(t.change_pct)}>{formatPercent(t.change_pct, 2)}</span>
  let value: ReactNode = "-", sub: ReactNode = day, viz: ReactNode = null
  if (t.value != null) switch (t.key) {
    case "breadth":
      value = <><span className="text-up-ink">{formatNumber(t.up)}</span><span className="text-base text-ink-3"> / </span><span className="text-down-ink">{formatNumber(t.down)}</span></>
      sub = `상승 · 하락 · 보합 ${formatNumber(t.flat)} · ${day}`
      viz = <BreadthBar up={t.up ?? 0} down={t.down ?? 0} flat={t.flat ?? 0} />
      break
    case "indiv_net":
      value = <span className={tone(t.value)}>{t.value > 0 ? "+" : ""}{formatKrw(t.value)}</span>
      sub = `매수 ${formatKrw(t.buy)} · 매도 ${formatKrw(t.sell)} · ${day} · 막대 20일`
      viz = <NetBars vals={t.series} />
      break
    case "usdkrw": case "dxy":
      value = formatLevel(t.value); sub = <>{pct} · {day} · 20일</>; viz = <Spark vals={t.series} />
      break
    case "wti":
      value = `$${formatLevel(t.value)}`; sub = <>{pct} · {day} · 20일</>; viz = <Spark vals={t.series} />
      break
    case "credit":
      value = formatKrw(t.value)
      sub = <>20일 <span className={tone(t.growth_20)}>{formatPercent(t.growth_20 == null ? null : t.growth_20 * 100)}</span> · 5년 백분위 {t.pctile == null ? "-" : Math.round(t.pctile)} · {day}</>
      viz = <Spark vals={t.series} />
      break
    case "fear_greed":
      value = Math.round(t.value); sub = `${fearGreedZone(t.value) ?? "-"} · ${day}`
      viz = <><GreedBar v={t.value} /><Spark vals={t.series} /></>
      break
    case "us10y":
      value = formatYield(t.value); sub = `2년 ${formatYield(t.second)} · ${day} · 20일`; viz = <Spark vals={t.series} />
      break
  }
  return <Card data-tile={t.key} className="min-h-0 min-w-0 gap-1.5 overflow-hidden rounded-[var(--radius-card)] px-4 py-3.5 shadow-none">
    <span className="flex items-center text-xs text-ink-3">{t.label}{TIPS[t.key] && <InfoTip label={`${t.label} 설명`}>{TIPS[t.key]}</InfoTip>}</span>
    <span className="font-display text-2xl leading-tight font-normal tracking-[-0.01em] tabular-nums">{value}</span>
    <span className="text-xs text-ink-2">{sub}</span>
    {viz && <div className="mt-auto flex flex-col gap-1.5">{viz}</div>}
  </Card>
}

function BreadthBar({ up, down, flat }: { up: number; down: number; flat: number }) {
  const tot = up + down + flat || 1
  return <div aria-hidden className="flex h-1.5 gap-0.5 overflow-hidden rounded-[3px]">
    <span className="bg-up" style={{ width: `${up / tot * 100}%` }} /><span className="bg-line-2" style={{ width: `${flat / tot * 100}%` }} /><span className="bg-down" style={{ width: `${down / tot * 100}%` }} />
  </div>
}

/** 20일 추이선 — 칸 폭을 채운다 */
function Spark({ vals }: { vals: number[] }) {
  if (vals.length < 2) return null
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * 200).toFixed(1)},${(32 - (v - lo) / ((hi - lo) || 1) * 30).toFixed(1)}`).join(" ")
  return <svg viewBox="0 0 200 34" preserveAspectRatio="none" className="h-[34px] w-full" aria-hidden><polyline points={pts} fill="none" className="stroke-ink-2" strokeWidth="1.4" vectorEffect="non-scaling-stroke" /></svg>
}

/** 0선 위아래 막대 — 순매수(+) 상승색, 순매도(−) 하락색 */
function NetBars({ vals }: { vals: number[] }) {
  if (!vals.length) return null
  const m = Math.max(...vals.map(Math.abs)) || 1
  const w = 200 / vals.length
  return <svg viewBox="0 0 200 34" preserveAspectRatio="none" className="h-[34px] w-full" aria-hidden>
    {vals.map((v, k) => <rect key={k} x={k * w + 1} y={v >= 0 ? 17 - v / m * 15 : 17} width={Math.max(0.5, w - 2)} height={Math.max(0.8, Math.abs(v) / m * 15)} className={v >= 0 ? "fill-up" : "fill-down"} />)}
    <line x1="0" x2="200" y1="17" y2="17" className="stroke-line-2" strokeWidth="1" vectorEffect="non-scaling-stroke" />
  </svg>
}

function GreedBar({ v }: { v: number }) {
  return <div aria-hidden className="relative h-1.5 rounded-[3px] bg-[linear-gradient(90deg,var(--down)_0%,var(--line-2)_50%,var(--up)_100%)]">
    <span className="absolute -top-[3px] h-3 w-0.5 bg-ink" style={{ left: `${Math.max(0, Math.min(100, v))}%` }} />
  </div>
}
