import { useEffect, useRef } from "react"
import { createChart, ColorType, LineStyle, PriceScaleMode } from "lightweight-charts"
import type { IChartApi, ISeriesApi, DeepPartial, ChartOptions, Time } from "lightweight-charts"
import { DEFAULT_CHART_OPTIONS } from "./LightweightChart"
import { chartOptions, useChartTheme } from "./chartTheme"

/** 선·막대 계열. color·posColor·negColor는 CSS 변수 이름(--chart-1 등) — 캔버스용으로 마운트 때 해석한다 */
export interface RegimeSeries {
  key: string
  label: string
  color: string
  data: { time: string; value: number }[]
  type?: "line" | "histogram"
  /** 막대일 때 양수·음수 색 */
  posColor?: string
  negColor?: string
  dashed?: boolean
  lineWidth?: 1 | 2 | 3
}

/** 날짜 구간 음영. color는 CSS 변수 이름. strip이면 바닥 띠로만 그린다(실시간 추세 등) */
export interface RegimeBandSpec {
  start: string
  end: string
  color: string
  /** 잠정 구간은 옅게 */
  faint?: boolean
  strip?: boolean
  title?: string
}

interface RegimeChartProps {
  series: RegimeSeries[]
  bands?: RegimeBandSpec[]
  height?: number
  logScale?: boolean
  formatValue?: (v: number) => string
  /** 0 기준선 */
  zeroLine?: boolean
}

const STRIP_H = 6

/** 국면 음영 차트 — lightweight-charts 위에 날짜 구간 div를 겹친다(CandlestickChart 선택 음영과 같은 좌표 동기화) */
export default function RegimeChart({ series, bands = [], height = 320, logScale, formatValue, zeroLine }: RegimeChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const layerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<"Line" | "Histogram">[]>([])
  const theme = useChartTheme()   // 테마가 바뀌면 토큰 색을 다시 읽어 차트를 다시 만든다
  const shapeKey = series.map(s => `${s.key}:${s.type ?? "line"}:${s.color}:${s.dashed ? 1 : 0}`).join("|")

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const opts: DeepPartial<ChartOptions> = {
      ...DEFAULT_CHART_OPTIONS,
      layout: { ...DEFAULT_CHART_OPTIONS.layout, background: { type: ColorType.Solid, color: "transparent" } },
      rightPriceScale: { ...DEFAULT_CHART_OPTIONS.rightPriceScale, mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal },
      timeScale: { ...DEFAULT_CHART_OPTIONS.timeScale, minBarSpacing: 0.01 },   // 수십 년 이력도 fitContent로 한 화면에
      width: container.clientWidth,
      height,
    }
    if (formatValue) opts.localization = { priceFormatter: formatValue }
    const chart = createChart(container, opts)
    chart.applyOptions(chartOptions(theme))
    chartRef.current = chart
    const css = getComputedStyle(container)
    const color = (token: string) => css.getPropertyValue(token).trim() || "#888"
    seriesRef.current = series.map(s => {
      const format = formatValue ? { type: "custom" as const, formatter: formatValue } : { type: "price" as const }
      return s.type === "histogram"
        ? chart.addHistogramSeries({ color: color(s.color), priceFormat: format, priceLineVisible: false, lastValueVisible: false })
        : chart.addLineSeries({ color: color(s.color), lineWidth: s.lineWidth ?? 2, lineStyle: s.dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceFormat: format, priceLineVisible: false })
    })
    if (zeroLine && seriesRef.current[0]) seriesRef.current[0].createPriceLine({ price: 0, color: color("--border"), lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: "" })
    const ro = new ResizeObserver(entries => { for (const e of entries) if (e.contentRect.width > 0) chart.applyOptions({ width: e.contentRect.width }) })
    ro.observe(container)
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = [] }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, shapeKey, logScale, zeroLine, theme])

  useEffect(() => {
    const chart = chartRef.current, container = containerRef.current
    if (!chart || !container) return
    const css = getComputedStyle(container)
    const color = (token: string) => css.getPropertyValue(token).trim() || "#888"
    series.forEach((s, i) => {
      const target = seriesRef.current[i]
      if (!target) return
      target.setData(s.type === "histogram"
        ? s.data.map(p => ({ time: p.time as Time, value: p.value, color: color(p.value >= 0 ? (s.posColor ?? s.color) : (s.negColor ?? s.color)) }))
        : s.data.map(p => ({ time: p.time as Time, value: p.value })))
    })
    chart.timeScale().fitContent()
  }, [series, theme])

  // 음영 — 구간 끝을 데이터에 있는 날짜로 맞춰 좌표를 잰다. 스크롤·확대·리사이즈 때 다시 잰다
  useEffect(() => {
    const chart = chartRef.current, layer = layerRef.current, container = containerRef.current
    if (!chart || !layer || !container) return
    const times = [...new Set(series.flatMap(s => s.data.map(p => p.time)))].sort()
    const sync = () => {
      layer.replaceChildren()
      if (!times.length) return
      const plotRight = container.clientWidth - chart.priceScale("right").width()
      for (const b of bands) {
        const from = times.find(t => t >= b.start), to = times.findLast(t => t <= b.end)
        if (!from || !to || from > to) continue
        const l = chart.timeScale().timeToCoordinate(from as Time), r = chart.timeScale().timeToCoordinate(to as Time)
        if (l == null || r == null) continue
        const left = Math.max(0, l), right = Math.min(plotRight, Math.max(r, l + 1))
        if (right <= left) continue
        const div = document.createElement("div")
        div.className = "absolute"
        div.style.left = `${left}px`
        div.style.width = `${right - left}px`
        if (b.strip) { div.style.bottom = "28px"; div.style.height = `${STRIP_H}px` } else { div.style.top = "0"; div.style.bottom = "28px" }
        div.style.background = `color-mix(in srgb, var(${b.color}) ${b.strip ? 70 : b.faint ? 7 : 14}%, transparent)`
        if (b.title) div.title = b.title
        layer.appendChild(div)
      }
    }
    sync()
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync)
    const ro = new ResizeObserver(sync)
    ro.observe(container)
    return () => { ro.disconnect(); chart.timeScale().unsubscribeVisibleLogicalRangeChange(sync) }
  }, [bands, series, height, shapeKey, logScale, theme])

  return <div className="relative">
    <div className="pointer-events-none absolute top-2 left-3 z-10 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
      {series.map(s => <span key={s.key} className="flex items-center gap-1">
        <span className="inline-block h-0.5 w-4" style={{ background: `var(${s.color})`, borderTop: s.dashed ? `1px dashed var(${s.color})` : undefined }} />{s.label}
      </span>)}
    </div>
    {/* 음영은 캔버스 아래 — 차트 배경이 투명이라 선 밑으로 비친다 */}
    <div ref={layerRef} aria-hidden="true" className="pointer-events-none absolute inset-0 z-0" />
    <div ref={containerRef} className="relative z-[1]" style={{ width: "100%", height }} />
  </div>
}
