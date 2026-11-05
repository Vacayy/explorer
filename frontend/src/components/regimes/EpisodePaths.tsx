import { useMemo } from "react"
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"
import { InfoTip } from "./Section"
import { formatPercent } from "@/utils/format"
import type { EraOutcome, EraSignal } from "@/types"

export const OUTCOME: Record<EraOutcome, { label: string; color: string; cls: string }> = {
  bear: { label: "약세장", color: "var(--down)", cls: "border-down/40 text-down-ink" },
  correction: { label: "−15% 이상 조정", color: "var(--chart-warning)", cls: "border-chart-warning/50 text-warn" },
  rebound: { label: "약세 직후 반등", color: "var(--chart-4)", cls: "text-muted-foreground" },
  false: { label: "헛경보", color: "var(--chart-gray)", cls: "text-muted-foreground" },
}
const ORDER: EraOutcome[] = ["bear", "correction", "rebound", "false"]
const TICKS = [0, 63, 126, 189, 252]
const tickLabel = (k: number) => (k === 0 ? "켜진 날" : k === 252 ? "1년" : `${k / 21}개월`)

/**
 * 과거 에피소드의 이후 경로 — 신호가 켜진 날을 100으로 두고 1년(252거래일) 뒤까지.
 * 얇은 선 = 각 에피소드(결과별 색), 굵은 선 = 결과별 중앙 경로, 검은 선 = 지금 진행 중인 에피소드.
 */
export function EpisodePaths({ signal, current, compact }: { signal: EraSignal; current?: [number, number][]; compact?: boolean }) {
  const eps = signal.episodes
  const rows = useMemo(() => {
    const byK = new Map<number, Record<string, number>>()
    const put = (k: number, key: string, v: number) => { const r = byK.get(k) ?? { k }; r[key] = v; byK.set(k, r) }
    eps.forEach((e, i) => e.path.forEach(([k, v]) => put(k, `e${i}`, v)))
    ORDER.forEach(o => signal.median_path[o]?.forEach(([k, v]) => put(k, `m_${o}`, v)))
    current?.forEach(([k, v]) => put(k, "now", v))
    return [...byK.values()].sort((a, b) => a.k - b.k)
  }, [eps, signal.median_path, current])
  const counts = ORDER.map(o => ({ o, n: eps.filter(e => e.outcome === o).length }))
  const median = (xs: number[]) => { const a = [...xs].sort((x, y) => x - y); return a.length ? (a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2) : null }
  const bearLow = median(eps.filter(e => e.outcome === "bear").map(e => e.min_after))
  const falseLow = median(eps.filter(e => e.outcome === "false").map(e => e.min_after))

  const note = <>켜진 날을 100으로 두고 1년 뒤까지 그렸습니다. 얇은 선은 각 에피소드, 굵은 선은 결과별 중앙 경로{current && current.length > 0 ? ", 검은 선은 지금 진행 중인 경로" : ""}입니다.
    {bearLow != null && <> 이후 1년 최저의 중앙값은 약세장이었던 경우 {formatPercent(bearLow)}, 헛경보였던 경우 {formatPercent(falseLow)}입니다(중앙 경로는 바닥 시점이 서로 달라 이보다 얕게 보입니다).</>}
    {" "}켜진 날 그것이 약세장인지 헛경보인지는 알 수 없습니다 — 색은 나중에 알게 된 결과입니다.</>
  const legend = <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted-foreground">
    {counts.map(({ o, n }) => <span key={o} className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4" style={{ background: OUTCOME[o].color }} />{OUTCOME[o].label} {n}번</span>)}
    {current && current.length > 0 ? <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-foreground" />지금</span> : <span>진행 중인 경로 없음</span>}
    <InfoTip label="에피소드 경로 읽는 법">{note}</InfoTip>
  </div>
  const chart = <div className={cn("h-[300px] w-full", compact && "h-[220px] min-w-[520px]")}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="k" type="number" domain={[0, 252]} ticks={TICKS} tickFormatter={tickLabel} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} width={44} tickFormatter={v => `${v - 100 > 0 ? "+" : ""}${Math.round(v - 100)}%`} />
          <ReferenceLine y={100} stroke="var(--muted-foreground)" strokeOpacity={0.6} />
          <ReferenceLine y={80} stroke="var(--down)" strokeDasharray="4 4" strokeOpacity={0.5} label={{ value: "−20%", position: "insideBottomLeft", fontSize: 10, fill: "var(--down)" }} />
          {eps.map((e, i) => <Line key={i} dataKey={`e${i}`} stroke={OUTCOME[e.outcome].color} strokeOpacity={0.28} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls />)}
          {ORDER.map(o => <Line key={o} dataKey={`m_${o}`} name={`${OUTCOME[o].label} 중앙`} stroke={OUTCOME[o].color} strokeWidth={3} dot={false} isAnimationActive={false} connectNulls />)}
          {current && current.length > 0 && <Line dataKey="now" name="지금" stroke="var(--foreground)" strokeWidth={2.5} dot={false} isAnimationActive={false} />}
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
