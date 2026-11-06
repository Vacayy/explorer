// 콜 상세의 실적 체인 섹션 — 발표 전 → 컨콜 → 시장 반응 → 그 뒤 (docs/specs/earnings-season.md §콜 상세)
// 데이터는 GET /chain/{id} 하나. 정성(기대·반응 구조화)이 없으면 칸마다 '없음'의 이유를 쓴다(Partial).
import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { InPlaceMore } from "@/components/shared/Bounded"
import { InfoTip } from "@/components/shared/InfoTip"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { usePinCore, useSeason } from "@/hooks/useTranscripts"
import { formatPercent } from "@/utils/format"
import { cn } from "@/lib/utils"
import { Bullets, Cols, DqHead, DqValue, Meta, Pp, SHORT_REASON, Section, VERDICT, VERDICT_CLS, WEIGHT, mmdd } from "@/components/follow/season/seasonUi"
import type { ChainDetail, ExpectationIssue, ReactionGrade, UpcomingChain } from "@/types"

const TOOLTIP_STYLE = { fontSize: 12, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" }
const CHART_MARGIN = { top: 18, right: 12, bottom: 0, left: 0 }
/** 근거 번호([39][13])는 이 화면에 출처 목록이 없어 지운다 — 전문·출처는 아래 펼치기 */
const clean = (s: string) => s.replace(/\s*\[\d+\]/g, "").trim()
const FOLLOW: Record<string, string> = { 유지: "유지됐다", 확대: "더 커졌다", 되돌림: "되돌려졌다", 반전: "뒤집혔다" }

/* ---------- 헤더: 섹터 링크 + 핵심 표시·고정 ---------- */
export function ChainHeaderLinks({ chain }: { chain: ChainDetail }) {
  const season = useSeason()
  const pin = usePinCore()
  const core = season.data?.core.tickers.find((t) => t.ticker === chain.ticker)
  const pinned = !!core?.reasons.includes("pinned")
  const criteria = season.data?.core.criteria
  const toggle = () => pin.mutate({ ticker: chain.ticker, pinned: !pinned }, {
    onSuccess: () => toast.success(pinned ? `${chain.ticker} 핵심 고정을 풀었습니다` : `${chain.ticker}를 핵심으로 고정했습니다`),
    onError: (e) => toast.error(e.message),
  })
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Link to={`/follow/transcripts?view=season&sector=${encodeURIComponent(chain.sector)}`} className="text-[13px] text-ink-2 hover:text-ink hover:underline whitespace-nowrap"
        title="이 섹터의 이번 시즌 반응 보기">{chain.sector_name} ›</Link>
      {core && (
        <Badge variant="neutral"
          title={criteria ? core.reasons.map((r) => criteria[r]).join(" · ") : undefined}>
          핵심 · {core.reasons.map((r) => SHORT_REASON[r]).join(" · ")}
        </Badge>
      )}
      {season.data && (
        <Button variant="ghost" size="xs" onClick={toggle} disabled={pin.isPending}
          title="핵심 종목은 발표 전 기대(D-7·D-1)와 시장 반응 정리가 자동으로 만들어집니다">
          {pin.isPending && <Spinner className="size-3" />}{pinned ? "고정 해제" : "핵심 고정"}
        </Button>
      )}
    </span>
  )
}

/* ---------- 발표 창 차트: D−6 ~ D+3 누적 수익률 (시안 Call-Detail · Mobile-Call) ----------
 * series.offset 0 = 발표일, 기준(0%) = 발표 전 마지막 거래일. 종목 = 글자색 굵은 선, 비교 ETF = 회색 점선, 발표 = 세로 점선. */
/* 시안은 640×200 SVG를 칸 폭으로 늘려 글자·선이 커진다 — 데스크톱은 그 크기(약 1.3배)로 */
const MONO_TICK = { fontSize: 10.5, fill: "var(--ink-3)", fontFamily: "var(--font-mono)" }
const MONO_TICK_LG = { ...MONO_TICK, fontSize: 13 }
const dLabel = (n: number) => (n === 0 ? "D" : n > 0 ? `D+${n}` : `D${n}`)
const signedPct = (v: number) => `${v > 0 ? "+" : ""}${v}%`

/** upcoming = 다가오는 발표 — 시세는 오늘(최근 종가)까지, 축은 발표일(0)까지 늘려 발표 표시가 앞쪽에 선다 */
export function CallWindowChart({ chain, compact = false, upcoming = false }: { chain: ChainDetail; compact?: boolean; upcoming?: boolean }) {
  const hi = compact ? 4 : 3
  const lastOff = chain.series.at(-1)?.offset ?? 0
  const rows = upcoming ? chain.series.filter((s) => s.offset >= Math.min(-6, lastOff - 9))
    : chain.series.filter((s) => s.offset >= -6 && s.offset <= hi)
  if (rows.length < 2) return <Meta>{upcoming ? "발표 전 시세가 아직 없습니다." : "발표 전후 시세가 아직 없습니다."}</Meta>
  const last = rows[rows.length - 1]
  const lo = rows[0].offset, end = upcoming ? 0 : last.offset
  const span = Math.max(...rows.flatMap((r) => [r.ret, r.bench])) - Math.min(...rows.flatMap((r) => [r.ret, r.bench])) || 1
  const close = Math.abs(last.ret - last.bench) < span * 0.08
  // 선 끝 라벨 — 데스크톱은 끝 점 오른쪽 이름만, 폰은 끝 점 위·아래 '이름 값'(낮은 선은 아래)
  const endLabel = (key: "ret" | "bench") => (p: { x?: number | string; y?: number | string; index?: number }) => {
    if (p.index !== rows.length - 1 || p.x == null || p.y == null) return <g />
    const x = Number(p.x), y = Number(p.y)
    const isRet = key === "ret"
    const below = isRet ? last.ret <= last.bench : last.bench < last.ret
    const name = isRet ? chain.ticker : chain.etf
    const fill = isRet ? "var(--ink)" : "var(--ink-3)"
    if (compact) {
      return <text x={x} y={below ? y + 14 : y - 6} textAnchor="end" fontSize={10.5} fill={fill} fontFamily="var(--font-mono)">
        {name}{upcoming ? "" : ` ${formatPercent(isRet ? last.ret : last.bench)}`}</text>
    }
    const dy = close ? (below ? 8 : -8) : 0
    return <text x={x + 8} y={y + 5 + dy} fontSize={13} fill={fill} fontWeight={isRet ? 600 : 400} fontFamily="var(--font-mono)">{name}</text>
  }
  const ev = chain.event_date
  return (
    <ResponsiveContainer width="100%" aspect={compact ? 358 / 150 : 640 / 200}>
      <LineChart data={rows} margin={compact ? { top: 8, right: 12, bottom: 0, left: 0 } : { top: 22, right: 76, bottom: 0, left: 0 }}>
        {!compact && <CartesianGrid stroke="var(--grid)" vertical={false} />}
        <XAxis type="number" dataKey="offset" domain={[lo, end]} ticks={upcoming ? [lo, 0] : [lo, 0, end]} tickFormatter={dLabel} tick={compact ? MONO_TICK : MONO_TICK_LG}
          axisLine={false} tickLine={false} interval={0} />
        <YAxis tick={compact ? MONO_TICK : MONO_TICK_LG} width={compact ? 26 : 56}
          domain={compact ? [(m: number) => m - span * 0.18, (m: number) => m + span * 0.05] : ["auto", "auto"]} tickCount={5} axisLine={false} tickLine={false}
          ticks={compact ? [0] : undefined} tickFormatter={(v: number) => (compact ? "0" : signedPct(v))} />
        <ReferenceLine y={0} stroke="var(--line-2)" strokeDasharray={compact ? "3 3" : undefined} />
        <ReferenceLine x={0} stroke={compact ? "var(--action)" : "var(--ink)"} strokeOpacity={compact ? 1 : 0.5} strokeDasharray="3 3"
          label={(p: { viewBox?: { x?: number; y?: number } }) => {
            const x = p.viewBox?.x ?? 0, y = p.viewBox?.y ?? 0
            return compact
              ? <text x={upcoming ? x - 4 : x + 4} y={y + 10} textAnchor={upcoming ? "end" : "start"} fontSize={10} fill="var(--action)">발표{ev ? ` ${mmdd(ev)}` : ""}</text>
              : <text x={x} y={y - 7} textAnchor={upcoming ? "end" : "middle"} fontSize={13} fill="var(--ink)" fontFamily="var(--font-mono)">발표{upcoming && ev ? ` ${mmdd(ev)}` : ""}</text>
          }} />
        <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(d) => dLabel(Number(d))} formatter={(v) => formatPercent(Number(v))} />
        <Line dataKey="bench" name={chain.etf} stroke="var(--ink-3)" strokeWidth={compact ? 1.4 : 1.8} strokeDasharray={compact ? "4 3" : "5 4"} dot={false} isAnimationActive={false}
          label={endLabel("bench")} />
        <Line dataKey="ret" name={chain.ticker} stroke="var(--ink)" strokeWidth={compact ? 1.8 : 2.6} isAnimationActive={false}
          dot={compact ? false : (p: { cx?: number; cy?: number; index?: number }) => p.index === rows.length - 1
            ? <circle key="end" cx={p.cx} cy={p.cy} r={4.5} fill="var(--ink)" /> : <g key={p.index} />}
          label={endLabel("ret")} />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** 지금 보는 분기의 기록 줄 (분기별 기록 표에서 transcript_id로, 없으면 맨 위) */
export const currentHistory = (chain: ChainDetail, transcriptId: number) =>
  chain.history.find((r) => r.transcript_id === transcriptId) ?? chain.history[0]
/** 'FY2026 Q3' → 'FY26 Q3' (시안 분기 라벨) */
export const fyShort = (s: string) => s.replace(/^FY20(\d\d)/, "FY$1")
/** 발표일부터 오늘까지 지난 날수 */
const daysSince = (iso: string) => {
  const d = new Date(iso + "T00:00:00"); const t = new Date(); t.setHours(0, 0, 0, 0)
  return Math.round((t.getTime() - d.getTime()) / 86_400_000)
}

/* ---------- 같은 날짜 축의 작은 차트 묶음: 주가 · 거래량 · 내 자료 언급 ---------- */
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`

export function ChainCharts({ chain }: { chain: ChainDetail }) {
  const { series, mentions, event_date: ev } = chain
  if (!series.length) return <Meta>시세가 아직 없습니다.</Meta>

  // 언급량은 'MM-DD'(한국 시각) — 발표일 연도로 붙이고, 반년 넘게 어긋나면 전년
  const year = Number((ev ?? series[0].date).slice(0, 4))
  const evMonth = Number((ev ?? series[0].date).slice(5, 7))
  const yearOf = (mm: number) => (mm - evMonth > 6 ? year - 1 : evMonth - mm > 6 ? year + 1 : year)
  const menIso = new Map(mentions.map((m) => [`${yearOf(Number(m.day.slice(0, 2)))}-${m.day}`, m.n]))
  const byDate = new Map(series.map((s) => [s.date, s]))
  const first = [series[0].date, ...menIso.keys()].sort()[0]
  const last = [series[series.length - 1].date, ...menIso.keys()].sort().slice(-1)[0]
  // 달력일 축 — 주말은 시세가 비고(선은 이어 그림) 언급량만 있다
  const rows: { day: string; ret: number | null; bench: number | null; vol: number | null; men: number | null; after: boolean }[] = []
  for (let d = new Date(first + "T00:00:00"); isoDay(d) <= last; d.setDate(d.getDate() + 1)) {
    const day = isoDay(d), s = byDate.get(day)
    rows.push({ day, ret: s?.ret ?? null, bench: s?.bench ?? null, vol: s?.volume != null ? s.volume / 1e6 : null, men: menIso.get(day) ?? null, after: !!ev && day >= ev })
  }
  const pre = series.filter((s) => s.offset < 0 && s.volume != null)
  const preAvg = pre.length ? pre.reduce((n, s) => n + s.volume!, 0) / pre.length / 1e6 : null
  const hasVol = rows.some((r) => r.vol != null)
  const hasMen = rows.some((r) => r.men != null)
  const evInAxis = !!ev && ev >= first && ev <= last
  const band = evInAxis && <ReferenceArea x1={ev!} x2={last} fill="var(--primary)" fillOpacity={0.06} ifOverflow="visible" />
  const evLine = (label?: string) => evInAxis && <ReferenceLine x={ev!} stroke="var(--primary)" strokeDasharray="3 3"
    label={label ? { value: label, position: "insideTopLeft", fontSize: 11, fontWeight: 600, fill: "var(--foreground)" } : undefined} />
  const xAxis = (show: boolean) => <XAxis dataKey="day" hide={!show} tick={AXIS_TICK} tickFormatter={(d: string) => mmdd(d)} minTickGap={28} />
  const title = (t: string) => <p className="text-caption font-semibold">{t}</p>

  return (
    <div className="space-y-1">
      {title("주가 (발표 전 마지막 거래일 = 0, 누적 %)")}
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={rows} syncId="chain" margin={CHART_MARGIN}>
          {band}{evLine(ev ? `발표 ${mmdd(ev)}` : undefined)}
          {xAxis(false)}
          <YAxis tick={AXIS_TICK} width={40} domain={["auto", "auto"]} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}`} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(d) => mmdd(String(d))} formatter={(v) => formatPercent(Number(v))} />
          <Line dataKey="bench" name={chain.etf} stroke="var(--series)" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls isAnimationActive={false} />
          <Line dataKey="ret" name={chain.ticker} stroke="var(--foreground)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      {hasVol && <>
        {title("거래량 (백만 주)")}
        <ResponsiveContainer width="100%" height={110}>
          <BarChart data={rows} syncId="chain" margin={CHART_MARGIN}>
            {band}{evLine()}
            {xAxis(false)}
            <YAxis tick={AXIS_TICK} width={40} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(d) => mmdd(String(d))} formatter={(v) => [`${Number(v).toFixed(1)}백만 주`, "거래량"]} />
            <Bar dataKey="vol" radius={2} isAnimationActive={false}>
              {rows.map((r) => <Cell key={r.day} fill={r.after ? "var(--primary)" : "var(--muted-foreground)"} fillOpacity={r.after ? 0.85 : 0.35} />)}
            </Bar>
            {preAvg != null && <ReferenceLine y={preAvg} stroke="var(--foreground)" strokeDasharray="2 3"
              label={{ value: `발표 전 평균 ${preAvg.toFixed(0)}`, position: "insideTopLeft", fontSize: 11, fontWeight: 600, fill: "var(--foreground)" }} />}
          </BarChart>
        </ResponsiveContainer>
      </>}
      {title(hasMen ? "내 자료 언급 (건/일, 한국 시각)" : "내 자료 언급 — 이 기간 자료 없음")}
      <ResponsiveContainer width="100%" height={hasMen ? 110 : 28}>
        <BarChart data={rows} syncId="chain" margin={{ ...CHART_MARGIN, top: hasMen ? 18 : 0 }}>
          {hasMen && band}{hasMen && evLine()}
          {xAxis(true)}
          <YAxis tick={hasMen ? AXIS_TICK : false} axisLine={hasMen} tickLine={hasMen} width={40} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(d) => mmdd(String(d))} formatter={(v) => [`${v}건`, "언급"]} />
          <Bar dataKey="men" radius={2} isAnimationActive={false}>
            {rows.map((r) => <Cell key={r.day} fill={r.after ? "var(--primary)" : "var(--muted-foreground)"} fillOpacity={r.after ? 0.85 : 0.35} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-caption text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-0.5 w-4 bg-foreground" />{chain.ticker}</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block w-4 border-t-2 border-dashed border-series" />{chain.etf} (비교)</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-sm bg-muted-foreground/35" />발표 전</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-sm bg-primary/85" />발표 후</span>
      </div>
    </div>
  )
}

/* ---------- 발표 전 / 컨콜 / 시장 반응 / 그 뒤 — 칸 넷(시안 Call-Detail, 칸마다 세 줄 이내 + 아래 배지) ---------- */
function Cell4({ step, title, children, badge, onMore }: { step: number; title: string; children: ReactNode; badge?: ReactNode; onMore?: () => void }) {
  return (
    <div className="-mr-px -mb-px flex min-w-0 flex-col">
      <Card className="flex-1 gap-3 p-4">
        <h2 className="flex items-baseline gap-2 text-[15px] font-semibold leading-snug">
          <span className="font-mono text-[11.5px] font-normal text-ink-3 tabular-nums">{step}</span>{title}</h2>
        <div className="flex flex-col gap-1 text-[13px] leading-[1.6]">{children}</div>
        {(badge || onMore) && <div className="mt-auto flex items-center justify-between gap-2">
          <span>{badge}</span>
          {onMore && <Button variant="ghost" size="sm" className="-mr-2 text-ink-2" aria-haspopup="dialog" onClick={onMore}>자세히 보기<ChevronRight aria-hidden="true" /></Button>}
        </div>}
      </Card>
    </div>
  )
}

/** 네 단계의 '자세히 보기' 내용 — 콜 상세가 단계 영역 위 물방울로 연다(D-331) */
export type StageKey = "before" | "call" | "reaction" | "after"
export type StageMore = (key: StageKey, title: string) => void
const Dots = ({ items }: { items: ReactNode[] }) => (
  <ul className="flex list-disc flex-col pl-4 text-[13px] leading-[1.6] marker:text-ink-3">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
)

export function StagesCard({ chain, transcriptId, onMore }: { chain: ChainDetail; transcriptId: number; onMore?: StageMore }) {
  const ex = chain.expectation
  const rm = chain.reaction_meta
  const h = currentHistory(chain, transcriptId)

  const before = <BeforeBody ex={ex} />

  const after: ReactNode[] = []
  if (h?.d1 != null) {
    after.push(<span key="d1">{h.follow ? `첫 반응이 ${FOLLOW[h.follow] ?? h.follow}` : "첫 반응"} — {chain.etf} 대비 첫 거래일 <Pp v={h.d1} />
      {h.d7 != null && <> → 일주일 <Pp v={h.d7} /></>}{h.d30 != null && <> · 한 달 <Pp v={h.d30} /></>}</span>)
  }
  const pt = chain.pt_after
  if (pt && pt.n > 0) {
    after.push(<span key="pt">발표 후 7일 목표가 변경 {pt.n}건 · 올림 {pt.up} · 내림 {pt.down}
      {pt.median_pct != null && <> · 중앙 <span className={cn("font-mono tabular-nums", pt.median_pct > 0 ? "text-up-ink" : pt.median_pct < 0 ? "text-down-ink" : "")}>{formatPercent(pt.median_pct)}</span></>}</span>)
    if (pt.examples.length) after.push(<span key="ex" className="text-xs text-ink-3">{pt.examples.slice(0, 2).join(" · ")}</span>)
  }
  const interim = chain.reaction_status === "interim"

  return (
    <div className="grid grid-cols-1 items-stretch pr-px pb-px md:grid-cols-2">
      <Cell4 step={1} title="발표 전" badge={ex && <Badge variant="hyp">{ex.snapshot === "d1" ? "전날" : "일주일 전"} 정리</Badge>}
        onMore={onMore && (() => onMore("before", "발표 전 시장이 주목한 내용"))}>{before}</Cell4>
      <Cell4 step={2} title="컨콜" onMore={onMore && (() => onMore("call", "핵심 정리 · 컨콜 전체"))}>
        {rm?.call_points?.length ? <Dots items={rm.call_points.slice(0, 3).map(clean)} /> : <Meta>아래 '핵심 정리'를 펼쳐 보세요.</Meta>}
      </Cell4>
      <Cell4 step={3} title="시장 반응" badge={interim && <Badge variant="warn">진행 중{chain.event_date ? ` · 발표 ${daysSince(chain.event_date)}일째` : ""}</Badge>}
        onMore={onMore && (() => onMore("reaction", "시장 반응 정리 · 출처"))}>
        {rm?.react_points?.length ? <Dots items={rm.react_points.slice(0, 2).map(clean)} /> : <Meta>아래 '시장 반응 정리'에서 정리를 만드세요.</Meta>}
      </Cell4>
      <Cell4 step={4} title="그 뒤" onMore={onMore && (() => onMore("after", "그 뒤 · 수익률과 목표가 변경"))}>{after.length ? after : <Meta>첫 거래일이 아직 반영되지 않았습니다.</Meta>}</Cell4>
    </div>
  )
}

/** 칸 '발표 전' — 쟁점 요지 두 줄, 없으면 시장 위치, 둘 다 없으면 숫자 */
function BeforeBody({ ex }: { ex: ChainDetail["expectation"] }) {
  return ex?.points?.length ? <Dots items={ex.points.slice(0, 2).map(clean)} />
    : ex?.positioning ? <span>{clean(ex.positioning)}</span>
    : <>
      <Meta>발표 전 기대 정리가 없습니다.</Meta>
      {ex?.quant && <QuantFacts q={ex.quant} />}
    </>
}

/* ---------- 다가오는 분기 — 칸 넷 중 '발표 전'만 채우고 나머지는 발표 뒤 ---------- */
/** 실제 일정: 매일 07:20 회차가 발표 8~5일 전(d7)과 발표 당일 아침(d1)에 만든다(pipeline/earnings_chain.py daily) */
const SCHEDULE_TIP = "핵심 종목은 시장이 주목하는 쟁점까지, 나머지는 컨센서스·주가·목표가 숫자만 정리합니다. 발표 당일 아침에 한 번 더 갱신합니다."
export function UpcomingStagesCard({ chain, onMore }: { chain: UpcomingChain; onMore?: StageMore }) {
  const ex = chain.expectation
  const later = <Meta>발표 후 채워집니다.</Meta>
  return (
    <div className="grid grid-cols-1 items-stretch pr-px pb-px md:grid-cols-2">
      <Cell4 step={1} title="발표 전" badge={ex && <Badge variant="hyp">{ex.snapshot === "d1" ? "전날" : "일주일 전"} 정리</Badge>}
        onMore={ex && onMore ? () => onMore("before", "발표 전 시장이 주목한 내용") : undefined}>
        {ex ? <BeforeBody ex={ex} /> : <span className="inline-flex items-center gap-1 text-ink-2">발표 전 정리는 D-8~D-5 아침에 만들어집니다.
          <InfoTip label="발표 전 정리 일정">{SCHEDULE_TIP}</InfoTip></span>}
      </Cell4>
      <Cell4 step={2} title="컨콜">{later}</Cell4>
      <Cell4 step={3} title="시장 반응">{later}</Cell4>
      <Cell4 step={4} title="그 뒤">{later}</Cell4>
    </div>
  )
}

/** 다가오는 분기 '발표 전 · 자세히 보기' — 쟁점과 호재·악재 기준, 숫자로 본 기대, 최근 30일 목표가 변경 */
export function UpcomingBeforeDetail({ chain }: { chain: UpcomingChain }) {
  const q = chain.expectation?.quant
  const pt = chain.pt_before
  return (
    <div className="flex flex-col gap-5">
      <IssuesRow chain={chain} expanded />
      {q && <div className="flex flex-col gap-2"><h3 className="text-sm font-semibold">숫자로 본 기대</h3><QuantFacts q={q} /></div>}
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">최근 30일 목표가 변경 {pt?.n ?? 0}건{pt && pt.n > 0 ? ` · 올림 ${pt.up} · 내림 ${pt.down}` : ""}</h3>
        {pt?.changes?.length ? <PtList changes={pt.changes} /> : <Meta>최근 30일 안에 받은 목표가 변경이 없습니다.</Meta>}
      </div>
    </div>
  )
}

function QuantFacts({ q }: { q: NonNullable<NonNullable<ChainDetail["expectation"]>["quant"]> }) {
  const facts: ReactNode[] = []
  if (q.eps_est != null) facts.push(<>EPS 컨센서스 ${q.eps_est.toFixed(2)}</>)
  if (q.runup30 != null) facts.push(<>30일 상승폭 {formatPercent(q.runup30)}{q.runup30_vs_etf != null && <> (업종 대비 <Pp v={q.runup30_vs_etf} />)</>}</>)
  if (q.pt30 && q.pt30.n > 0) facts.push(<>30일 목표가 변경 {q.pt30.n}건(올림 {q.pt30.up}·내림 {q.pt30.down})</>)
  if (q.implied_move != null) facts.push(<>옵션 내재 변동폭 ±{q.implied_move.toFixed(1)}%</>)
  return facts.length ? <Bullets items={facts} /> : null
}

/* ---------- 발표 전 시장이 주목한 내용 — 한 줄씩(쟁점 | 중요도 | 결과 한 줄 | 영향), 기준·판정은 행을 눌러 펼침 ---------- */
const IMPACT: Record<string, string> = { major: "영향 큼", minor: "영향 작음", none: "영향 없음" }

/** expanded = 콜 상세 '발표 전 · 자세히 보기' 패널 안 — 제목은 패널 머리가 갖고, 모든 행을 펼친 채로 보인다 */
export function IssuesCard({ chain, expanded }: { chain: ChainDetail; expanded?: boolean }) {
  const ex = chain.expectation
  const grades = chain.reaction_meta?.grades ?? []
  const missed = chain.reaction_meta?.missed ?? []
  const byIssue = new Map((ex?.issues ?? []).map((i) => [i.issue, i]))
  // 행 펼침(기준·판정)은 한 번에 한 행, 목록 안에서 — 펼치기 직전 높이 그대로 안에서 스크롤(아래 블록이 밀리지 않게)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const rowProps = (key: string) => ({ open: expanded || openKey === key, always: expanded, onOpenChange: (v: boolean) => setOpenKey(v ? key : null) })
  const wrap = (list: ReactNode) => expanded ? list : <InPlaceMore open={openKey != null} size="md">{list}</InPlaceMore>

  let content: ReactNode
  if (!ex) content = <Meta>발표 전 기대가 정리되지 않은 발표입니다.</Meta>
  else if (grades.length || missed.length) {
    content = wrap(<ul className="flex flex-col">
      {grades.map((g) => <IssueRow key={g.issue} grade={g} issue={byIssue.get(g.issue)} {...rowProps(g.issue)} />)}
      {missed.map((m) => <IssueRow key={m} missed={clean(m)} {...rowProps(`missed:${m}`)} />)}
    </ul>)
  } else if (ex.issues?.length) {
    // 기대는 있는데 채점 전 — 쟁점과 기준만
    content = <>
      {wrap(<ul className="flex flex-col">{ex.issues.map((i) => <IssueRow key={i.issue} issue={i} {...rowProps(i.issue)} />)}</ul>)}
      <Meta>채점은 시장 반응 정리가 만들어지면 붙습니다.</Meta>
    </>
  } else content = <Meta>발표 전 정리에 쟁점이 없습니다.</Meta>

  return expanded ? <div className="flex flex-col gap-2">{content}</div> : <Section title="발표 전 시장이 주목한 내용">{content}</Section>
}

function IssueRow({ grade, issue, missed, open, always, onOpenChange: setOpen }: { grade?: ReactionGrade; issue?: ExpectationIssue; missed?: string
  open: boolean; always?: boolean; onOpenChange: (v: boolean) => void }) {
  const name = missed ?? grade?.issue ?? issue?.issue ?? ""
  const weight = grade?.weight ?? issue?.weight
  const result = missed ? "발표 전 정리에 없던 쟁점입니다." : grade?.outcome ?? (issue?.good ? `호재면 ${issue.good}` : "")
  const detail: ReactNode[] = []
  if (issue?.good || issue?.bad) detail.push(<>발표 전 기준: {issue.good && <>호재면 {issue.good}</>}{issue.good && issue.bad && " / "}{issue.bad && <>악재면 {issue.bad}</>}</>)
  if (grade?.verdict) detail.push(<>판정: <Badge className={cn("font-normal", VERDICT_CLS[grade.verdict])}>{VERDICT[grade.verdict]}</Badge></>)
  if (missed) detail.push(<>판정: <Badge className={cn("font-normal", VERDICT_CLS.missed)}>{VERDICT.missed}</Badge></>)
  const row = (
    <>
      <span className="flex min-w-0 items-baseline gap-1 text-[13px]">
        {detail.length > 0 && !always && <ChevronRight className={cn("size-3 shrink-0 self-center text-ink-3 transition-transform", open && "rotate-90")} />}{name}
      </span>
      <span>{weight && <Badge variant={weight === "high" ? "neutral" : "outline"}>{WEIGHT[weight]}</Badge>}</span>
      <span className="min-w-0 text-[12.5px] text-ink-2 max-md:col-span-2">{result}</span>
      <span>{grade?.drove && <Badge variant="outline">{IMPACT[grade.drove] ?? grade.drove}</Badge>}</span>
    </>
  )
  const grid = "grid w-full grid-cols-[1fr_auto] items-baseline gap-x-3 gap-y-1 py-2.5 text-left md:grid-cols-[1fr_auto_2fr_auto]"
  return (
    <li className="min-w-0 border-t border-line first:border-t-0">
      {detail.length && always ? (
        <><div className={grid}>{row}</div><div className="pb-2.5"><Bullets items={detail} /></div></>
      ) : detail.length ? (
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className={cn(grid, "cursor-pointer hover:bg-chip/40")}>{row}</CollapsibleTrigger>
          <CollapsibleContent className="pb-2.5 pl-4"><Bullets items={detail} /></CollapsibleContent>
        </Collapsible>
      ) : <div className={grid}>{row}</div>}
    </li>
  )
}

/* ---------- 지난 분기와 비교 (직전 분기 체인이 있을 때만) ---------- */
export function VsPrevCard({ chain }: { chain: ChainDetail }) {
  const v = chain.reaction_meta?.vs_prev
  if (!v?.length) return null
  return <Section title="지난 분기와 비교"><Bullets lead items={v.map(clean)} /></Section>
}

/** 쟁점 카드 + 지난 분기 비교 — 비교가 있으면 2단 */
export function IssuesRow({ chain, expanded }: { chain: ChainDetail; expanded?: boolean }) {
  if (expanded) return <div className="flex flex-col gap-5"><IssuesCard chain={chain} expanded />{chain.reaction_meta?.vs_prev?.length ? <VsPrevCard chain={chain} /> : null}</div>
  return chain.reaction_meta?.vs_prev?.length
    ? <Cols><IssuesCard chain={chain} /><VsPrevCard chain={chain} /></Cols>
    : <IssuesCard chain={chain} />
}

/* ---------- 분기별 기록 (표는 여기 한 곳만) ---------- */
export function HistoryCard({ chain, transcriptId, onSelect }: { chain: ChainDetail; transcriptId: number; onSelect: (id: number) => void }) {
  if (!chain.history.length) return null
  return (
    <Section title={<span className="inline-flex items-center gap-1">분기별 기록<InfoTip label="분기별 기록 설명">%p는 {chain.etf} 대비 초과수익이고, 목표가는 발표 후 7일 안의 변경 건수입니다.</InfoTip></span>}>
      <div className="overflow-x-auto">
        <Table className="text-sm">
          <TableHeader>
            <TableRow>
              <TableHead>분기</TableHead><TableHead>발표일</TableHead>
              <TableHead className="text-right">첫 거래일</TableHead><TableHead className="text-right">일주일</TableHead>
              <TableHead className="text-right"><DqHead etf={chain.etf} /></TableHead><TableHead className="text-right">목표가 올림·내림</TableHead><TableHead>반응 한 줄</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {chain.history.map((r) => {
              const cur = r.transcript_id === transcriptId
              return (
                <TableRow key={`${r.fiscal}-${r.event_date}`} className={cn(cur && "bg-primary/5 hover:bg-primary/5")}>
                  <TableCell className="font-semibold whitespace-nowrap">{r.fiscal}</TableCell>
                  <TableCell className="tabular-nums whitespace-nowrap">{mmdd(r.event_date)}</TableCell>
                  <TableCell className="text-right"><Pp v={r.d1} /></TableCell>
                  <TableCell className="text-right"><Pp v={r.d7} /></TableCell>
                  <TableCell className="text-right"><DqValue v={r.dq} partial={r.dq_partial} /></TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {r.pt_up == null && r.pt_down == null ? <span className="text-muted-foreground">-</span>
                      : <><span className="text-up-ink">{r.pt_up ?? 0}</span> · <span className="text-down-ink">{r.pt_down ?? 0}</span></>}
                  </TableCell>
                  <TableCell className="min-w-56 whitespace-normal">
                    {r.headline ?? <span className="inline-flex flex-wrap items-center gap-1.5 text-muted-foreground">
                      정리 없음
                      {r.transcript_id && !cur && <Button variant="ghost" size="xs" onClick={() => onSelect(r.transcript_id!)}>이 분기 보기</Button>}
                    </span>}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </Section>
  )
}

/** '그 뒤 · 자세히 보기' — 첫 거래일 · 일주일 · 한 달 · 분기 수익률(업종 ETF 대비) + 발표 후 7일 목표가 변경 전체 */
export function AfterDetail({ chain, transcriptId }: { chain: ChainDetail; transcriptId: number }) {
  const h = currentHistory(chain, transcriptId)
  const pt = chain.pt_after
  const cells: [string, number | null | undefined, string?][] = [
    ["첫 거래일", h?.d1], ["일주일", h?.d7], ["한 달", h?.d30], ["분기 수익률", h?.dq, h?.dq_partial ? "진행 중" : undefined]]
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 pr-px pb-px sm:grid-cols-4">
        {cells.map(([k, v, note]) => (
          <div key={k} className="-mr-px -mb-px flex flex-col gap-1 border border-line p-3">
            <span className="text-xs text-ink-3">{k} · {chain.etf} 대비</span>
            <span className="font-mono text-lg tabular-nums">{v == null ? "-" : <Pp v={v} />}</span>
            {note && <span className="text-xs text-ink-3">{note}</span>}
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">발표 후 7일 목표가 변경 {pt?.n ?? 0}건{pt && pt.n > 0 ? ` · 올림 ${pt.up} · 내림 ${pt.down}` : ""}</h3>
        {pt?.changes?.length ? <PtList changes={pt.changes} /> : <Meta>발표 후 7일 안에 받은 목표가 변경이 없습니다.</Meta>}
      </div>
    </div>
  )
}

function PtList({ changes }: { changes: NonNullable<NonNullable<ChainDetail["pt_after"]>["changes"]> }) {
  return (
    <ul className="flex flex-col">
      {changes.map((c, i) => (
        <li key={i} className="grid grid-cols-[56px_minmax(0,1fr)_auto_64px] items-baseline gap-3 border-b border-line py-2 text-[13px]">
          <span className="font-mono text-xs text-ink-3">{c.date.slice(5).replace("-", "/")}</span>
          <span className="truncate">{c.firm}</span>
          <span className="font-mono tabular-nums text-ink-2">${c.pt_from.toFixed(0)} → ${c.pt_to.toFixed(0)}</span>
          <span className={cn("text-right font-mono tabular-nums", c.pct > 0 ? "text-up-ink" : c.pct < 0 ? "text-down-ink" : "")}>{formatPercent(c.pct)}</span>
        </li>
      ))}
    </ul>
  )
}
