import { useMemo } from "react"
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, usePlotArea, useYAxisScale } from "recharts"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"
import { InfoTip } from "./Section"
import { formatPercent } from "@/utils/format"
import type { EraOutcome, EraSignal } from "@/types"

export const OUTCOME: Record<EraOutcome, { label: string; color: string; cls: string }> = {
  bear: { label: "약세장", color: "var(--down)", cls: "border-down/40 text-down-ink" },
  correction: { label: "−15% 이상 조정", color: "var(--warn)", cls: "border-chart-warning/50 text-warn" },
  rebound: { label: "약세 직후 반등", color: "var(--hyp)", cls: "text-muted-foreground" },
  false: { label: "헛경보", color: "var(--ink-3)", cls: "text-muted-foreground" },
}
const ORDER: EraOutcome[] = ["bear", "correction", "rebound", "false"]
const TICKS = [0, 63, 126, 189, 252]
const tickLabel = (k: number) => (k === 0 ? "켜진 날" : k === 252 ? "1년" : `${k / 21}개월`)

/**
 * 과거 에피소드의 이후 경로 — 신호가 켜진 날을 100으로 두고 1년(252거래일) 뒤까지.
 * 얇은 선 = 각 에피소드(결과별 색, 옅게), 굵은 선 = 결과별 중앙 경로 + 선 끝 라벨(결과 · 횟수 · 1년 뒤), 점선 = 지금 진행 중인 경로
 * (없으면 가장 최근 에피소드) — 시안 Home-Macro.
 */
export function EpisodePaths({ signal, current, compact }: { signal: EraSignal; current?: [number, number][]; compact?: boolean }) {
  const eps = signal.episodes
  const rows = useMemo(() => {
    const byK = new Map<number, Record<string, number>>()
    const put = (k: number, key: string, v: number) => { const r = byK.get(k) ?? { k }; r[key] = v; byK.set(k, r) }
    eps.forEach((e, i) => e.path.forEach(([k, v]) => put(k, `e${i}`, v)))
    ORDER.forEach(o => signal.median_path[o]?.forEach(([k, v]) => put(k, `m_${o}`, v)))
    const dashed = current && current.length > 0 ? current : eps.at(-1)?.path
    dashed?.forEach(([k, v]) => put(k, "now", v))
    return [...byK.values()].sort((a, b) => a.k - b.k)
  }, [eps, signal.median_path, current])
  const live = !!current && current.length > 0
  const latest = eps.at(-1)
  // 선 끝 라벨 — 결과별 중앙 경로의 마지막 값
  const ends = ORDER.flatMap(o => { const p = signal.median_path[o]; const last = p?.at(-1); return last ? [{ o, v: last[1], n: eps.filter(e => e.outcome === o).length }] : [] })
  const median = (xs: number[]) => { const a = [...xs].sort((x, y) => x - y); return a.length ? (a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2) : null }
  const bearLow = median(eps.filter(e => e.outcome === "bear").map(e => e.min_after))
  const falseLow = median(eps.filter(e => e.outcome === "false").map(e => e.min_after))

  const note = <>켜진 날을 100으로 두고 1년 뒤까지 그렸습니다. 얇은 선은 각 에피소드, 굵은 선은 결과별 중앙 경로, 점선은 {current && current.length > 0 ? "지금 진행 중인 경로" : "가장 최근 에피소드"}입니다.
    {bearLow != null && <> 이후 1년 최저의 중앙값은 약세장이었던 경우 {formatPercent(bearLow)}, 헛경보였던 경우 {formatPercent(falseLow)}입니다(중앙 경로는 바닥 시점이 서로 달라 이보다 얕게 보입니다).</>}
    {" "}켜진 날 그것이 약세장인지 헛경보인지는 알 수 없습니다 — 색은 나중에 알게 된 결과입니다.</>
  const legend = <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
    <span>{live ? "점선 = 지금 진행 중인 경로" : latest ? `점선 = 가장 최근 에피소드(${latest.date}, ${OUTCOME[latest.outcome].label}) · 진행 중인 경로 없음` : "진행 중인 경로 없음"}</span>
    <InfoTip label="에피소드 경로 읽는 법">{note}</InfoTip>
  </div>
  const chart = <div className={cn("h-[300px] w-full", compact && "h-[220px] min-w-[520px]")}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 8, right: compact ? 12 : 196, bottom: 4, left: -8 }}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="k" type="number" domain={[0, 252]} ticks={TICKS} tickFormatter={tickLabel} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} width={44} tickFormatter={v => `${v - 100 > 0 ? "+" : ""}${Math.round(v - 100)}%`} />
          <ReferenceLine y={100} stroke="var(--ink-3)" strokeDasharray="4 3" />
          {eps.map((e, i) => <Line key={i} dataKey={`e${i}`} stroke={OUTCOME[e.outcome].color} strokeOpacity={0.28} strokeWidth={0.8} dot={false} activeDot={false} isAnimationActive={false} connectNulls />)}
          {ORDER.map(o => <Line key={o} dataKey={`m_${o}`} name={`${OUTCOME[o].label} 중앙`} stroke={OUTCOME[o].color} strokeWidth={2.4} dot={false} isAnimationActive={false} connectNulls />)}
          <Line dataKey="now" name={live ? "지금" : "가장 최근"} stroke="var(--ink)" strokeWidth={1.6} strokeDasharray="5 3" dot={false} isAnimationActive={false} connectNulls />
          {!compact && <EndLabels ends={ends} />}
          <Tooltip isAnimationActive={false}
            content={({ active, payload, label }) => {
              if (!active || !payload) return null
              const shown = payload.filter(p => String(p.dataKey).startsWith("m_") || p.dataKey === "now")
              return <div className="rounded-lg border bg-popover px-2.5 py-1.5 text-caption shadow-md">
                <div className="mb-1 font-medium">{tickLabel(Number(label)) === "켜진 날" ? "켜진 날" : `켜진 뒤 ${label}거래일`}</div>
                {shown.map(p => <div key={String(p.dataKey)} className="flex justify-between gap-3"><span>{p.name}</span><span className="tabular-nums">{formatPercent(Number(p.value) - 100)}</span></div>)}
              </div>
            }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  if (compact) return <div className="space-y-2">{legend}<div className="-mx-1 overflow-x-auto px-1">{chart}</div></div>

  return <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
    <div className="min-w-0 space-y-2">{legend}{chart}</div>
    <div className="min-w-0 space-y-1.5">
      <p className="text-sm font-medium">최근 에피소드 6개</p>
      <Table>
        <TableHeader><TableRow>
          <TableHead>켜진 날</TableHead><TableHead>결과</TableHead><TableHead className="text-right">켜질 때 낙폭</TableHead>
          <TableHead className="text-right">이후 최저</TableHead><TableHead className="text-right">1년 뒤</TableHead>
        </TableRow></TableHeader>
        <TableBody>{[...eps].reverse().slice(0, 6).map(e => <TableRow key={e.date}>
          <TableCell className="tabular-nums">{e.date}</TableCell>
          <TableCell><Badge variant="outline" className={cn("font-normal", OUTCOME[e.outcome].cls)}>{OUTCOME[e.outcome].label}</Badge></TableCell>
          <TableCell className="text-right tabular-nums">{formatPercent(e.drawdown_at)}</TableCell>
          <TableCell className="text-right tabular-nums text-down-ink">{formatPercent(e.min_after)}</TableCell>
          <TableCell className="text-right tabular-nums">{e.ret_after == null ? "진행 중" : formatPercent(e.ret_after)}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </div>
  </div>
}

/** 결과별 중앙 경로 선 끝 라벨(시안 Home-Macro) — '● 약세장 16번 · −6%'. 겹치면 14px 간격으로 벌린다 */
function EndLabels({ ends }: { ends: { o: EraOutcome; v: number; n: number }[] }) {
  const area = usePlotArea()
  const y = useYAxisScale()
  if (!area || !y) return null
  const pts = ends.map(e => ({ ...e, y: Number(y(e.v)) })).sort((a, b) => a.y - b.y)
  pts.forEach((p, i) => { if (i > 0 && p.y - pts[i - 1].y < 14) p.y = pts[i - 1].y + 14 })
  const x = area.x + area.width + 8
  return <g>{pts.map(p => <text key={p.o} x={x} y={p.y + 4} fontSize={11.5} fill="var(--ink-2)">
    <tspan fill={OUTCOME[p.o].color}>●</tspan> {OUTCOME[p.o].label} {p.n}번 · {formatPercent(p.v - 100)}
  </text>)}</g>
}
