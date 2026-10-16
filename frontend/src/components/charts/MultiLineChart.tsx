import { useRef, useEffect, useMemo, useState } from "react"
import { X } from "lucide-react"
import { createChart, ColorType, LineStyle } from "lightweight-charts"
import type { IChartApi, ISeriesApi, DeepPartial, ChartOptions } from "lightweight-charts"
import { Button } from "@/components/ui/button"
import { DEFAULT_CHART_OPTIONS } from "./LightweightChart"

interface LineConfig {
  key: string
  label: string
  color: string
  lineWidth?: number
  lineStyle?: number // 0=Solid, 2=Dashed
}

interface MultiLineChartProps {
  data: Record<string, unknown>[]
  lines: LineConfig[]
  height?: number
  formatValue?: (value: number) => string
  /** 지정하면 차트를 눌렀을 때 그 날짜 기준 1일·1주·1개월 변화를 이 포맷으로 표시한다 */
  formatChange?: (delta: number) => string
}

/** 같은 일자의 한 달 전(말일은 그 달 말일로 맞춤) */
function monthBefore(day: string): string {
  const [y, m, d] = day.split("-").map(Number)
  const last = new Date(Date.UTC(y, m - 1, 0)).getUTCDate()
  return new Date(Date.UTC(y, m - 2, Math.min(d, last))).toISOString().slice(0, 10)
}

function daysBefore(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

const CHANGE_COLUMNS = [
  { key: "d", label: "1일" },
  { key: "w", label: "1주" },
  { key: "m", label: "1개월" },
] as const

export default function MultiLineChart({
  data,
  lines,
  height = 350,
  formatValue,
  formatChange,
}: MultiLineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesMapRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map())
  const changeEnabledRef = useRef(!!formatChange)
  changeEnabledRef.current = !!formatChange
  const [picked, setPicked] = useState<string | null>(null)
  const [pickedX, setPickedX] = useState<number | null>(null)
  // 사용자가 끌어 옮긴 변화 박스 위치(컨테이너 기준). 닫을 때까지 유지
  const [boxPos, setBoxPos] = useState<{ left: number; top: number } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  // Stable key for lines config to detect structural changes
  const linesKey = lines.map((l) => `${l.key}:${l.color}:${l.lineWidth ?? 2}:${l.lineStyle ?? 0}`).join("|")

  // Create chart and series
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const opts: DeepPartial<ChartOptions> = {
      ...DEFAULT_CHART_OPTIONS,
      layout: {
        ...DEFAULT_CHART_OPTIONS.layout,
        background: { type: ColorType.Solid, color: "transparent" },
      },
      width: container.clientWidth,
      height,
    }

    if (formatValue) {
      opts.localization = { priceFormatter: formatValue }
    }

    const chart = createChart(container, opts)
    chartRef.current = chart

    const map = new Map<string, ISeriesApi<"Line">>()
    for (const line of lines) {
      const series = chart.addLineSeries({
        color: line.color,
        lineWidth: (line.lineWidth ?? 2) as 1 | 2 | 3 | 4,
        lineStyle: line.lineStyle ?? LineStyle.Solid,
        priceFormat: formatValue
          ? { type: "custom", formatter: formatValue }
          : { type: "price" },
      })
      map.set(line.key, series)
    }
    seriesMapRef.current = map

    // 클릭한 날짜 → 변화 오버레이 (formatChange 지정 시만)
    chart.subscribeClick((param) => {
      if (!changeEnabledRef.current) return
      const t = param.time
      if (t == null) { setPicked(null); setBoxPos(null); return }
      setPicked(typeof t === "object" ? `${t.year}-${String(t.month).padStart(2, "0")}-${String(t.day).padStart(2, "0")}` : typeof t === "number" ? new Date(t * 1000).toISOString().slice(0, 10) : t)
    })

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect
        if (width > 0) chart.applyOptions({ width })
      }
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      seriesMapRef.current = new Map()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, linesKey])

  // Update data
  useEffect(() => {
    if (!chartRef.current || data.length === 0) return

    for (const line of lines) {
      const series = seriesMapRef.current.get(line.key)
      if (!series) continue

      const seriesData = data
        .filter((d) => d.time != null && d[line.key] != null)
        .map((d) => ({
          time: d.time as string,
          value: d[line.key] as number,
        }))

      series.setData(seriesData)
    }

    chartRef.current.timeScale().fitContent()
  }, [data, lines])

  // 고른 날짜의 화면 x좌표 — 스크롤·확대·리사이즈에 따라 다시 잰다
  useEffect(() => {
    const chart = chartRef.current, container = containerRef.current
    if (!chart || !container || !picked) { setPickedX(null); return }
    const sync = () => setPickedX(chart.timeScale().timeToCoordinate(picked))
    sync()
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync)
    const ro = new ResizeObserver(sync)
    ro.observe(container)
    return () => { ro.disconnect(); chart.timeScale().unsubscribeVisibleLogicalRangeChange(sync) }
  }, [picked, data, height, linesKey])

  const changes = useMemo(() => {
    if (!picked || !formatChange) return []
    return lines.flatMap((line) => {
      const pts = data
        .filter((d) => d.time != null && d[line.key] != null)
        .map((d) => ({ time: d.time as string, value: d[line.key] as number }))
      const i = pts.findLastIndex((p) => p.time <= picked)
      if (i < 0) return []
      const base = pts[i]
      const at = (target: string) => pts.findLast((p) => p.time <= target)
      const ref = { d: pts[i - 1], w: at(daysBefore(base.time, 7)), m: at(monthBefore(base.time)) }
      return [{ line, delta: Object.fromEntries(CHANGE_COLUMNS.map((c) => [c.key, ref[c.key] ? base.value - ref[c.key]!.value : null])) as Record<"d" | "w" | "m", number | null> }]
    })
  }, [picked, data, lines, formatChange])

  const tone = (v: number | null) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up" : "text-down"
  const close = () => { setPicked(null); setBoxPos(null) }

  const startDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const box = boxRef.current, container = containerRef.current
    if (!box || !container || (e.target as HTMLElement).closest("button")) return
    e.preventDefault()
    const handle = e.currentTarget
    handle.setPointerCapture(e.pointerId)
    const start = { x: e.clientX, y: e.clientY, left: box.offsetLeft, top: box.offsetTop }
    const maxLeft = container.clientWidth - box.offsetWidth, maxTop = height - box.offsetHeight
    const move = (ev: PointerEvent) => setBoxPos({
      left: Math.min(Math.max(0, start.left + ev.clientX - start.x), maxLeft),
      top: Math.min(Math.max(0, start.top + ev.clientY - start.y), maxTop),
    })
    const end = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", end); handle.removeEventListener("pointercancel", end) }
    handle.addEventListener("pointermove", move)
    handle.addEventListener("pointerup", end)
    handle.addEventListener("pointercancel", end)
  }

  const flip = pickedX != null && containerRef.current != null && pickedX > containerRef.current.clientWidth / 2

  return (
    <div style={{ position: "relative" }}>
      {/* Legend overlay */}
      <div
        style={{
          position: "absolute",
          top: 8,
          left: 12,
          zIndex: 10,
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          fontSize: 11,
          color: "#6b7280",
        }}
      >
        {lines.map((line) => (
          <span key={line.key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span
              style={{
                display: "inline-block",
                width: 16,
                height: 2,
                backgroundColor: line.color,
                borderStyle: line.lineStyle === 2 ? "dashed" : "solid",
              }}
            />
            {line.label}
          </span>
        ))}
      </div>
      <div ref={containerRef} style={{ width: "100%", height }} />
      {formatChange && picked && pickedX != null && changes.length > 0 && <>
        <div aria-hidden="true" className="pointer-events-none absolute top-0 bottom-8 w-px border-l border-dashed border-foreground/40" style={{ left: pickedX }} />
        <div
          role="dialog"
          aria-label={`${picked} 기준 변화`}
          ref={boxRef}
          className="absolute z-20 rounded-lg border bg-popover p-2.5 text-caption text-popover-foreground shadow-md"
          style={boxPos ?? (flip ? { top: 32, right: `calc(100% - ${pickedX - 8}px)` } : { top: 32, left: pickedX + 8 })}
        >
          <div className="mb-1.5 flex cursor-grab touch-none select-none items-center justify-between gap-4 active:cursor-grabbing" onPointerDown={startDrag} title="끌어서 옮기기">
            <span className="font-medium">{picked} 기준 변화</span>
            <Button variant="ghost" size="icon" className="size-5" aria-label="닫기" onClick={close}><X className="size-3" /></Button>
          </div>
          <div className="grid items-center gap-x-3 gap-y-1" style={{ gridTemplateColumns: "auto repeat(3, auto)" }}>
            <span />
            {CHANGE_COLUMNS.map((c) => <span key={c.key} className="text-right text-muted-foreground">{c.label}</span>)}
            {changes.map(({ line, delta }) => [
              <span key={line.key} className="flex items-center gap-1.5 whitespace-nowrap">
                <span className="size-2 rounded-full" style={{ background: line.color }} aria-hidden="true" />{line.label}
              </span>,
              ...CHANGE_COLUMNS.map((c) => <span key={`${line.key}-${c.key}`} className={`text-right tabular-nums ${tone(delta[c.key])}`}>{delta[c.key] == null ? "-" : formatChange(delta[c.key]!)}</span>),
            ])}
          </div>
        </div>
      </>}
    </div>
  )
}

export type { LineConfig, MultiLineChartProps }
