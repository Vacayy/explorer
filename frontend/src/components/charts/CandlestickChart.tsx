import { useRef, useEffect } from "react"
import { createChart, ColorType, LineStyle } from "lightweight-charts"
import type { IChartApi, ISeriesApi, DeepPartial, ChartOptions } from "lightweight-charts"
import { DEFAULT_CHART_OPTIONS } from "./LightweightChart"

export interface ChartMarker {
  time: string
  direction: "up" | "down"
  text: string
}

interface CandlestickChartProps {
  data: { time: string; open: number; high: number; low: number; close: number }[]
  volumeData?: { time: string; value: number; color: string }[]
  markers?: ChartMarker[]
  onMarkerClick?: (time: string) => void
  selectedTime?: string
  selectionStart?: string
  height?: number
  formatValue?: (value: number) => string
  overlays?: { id: string; title: string; token: string; data: { time: string; value: number }[]; dashed?: boolean }[]
}

// Korean stock convention: red = up, blue = down
const UP_COLOR = "#ef4444"
const DOWN_COLOR = "#3b82f6"

export default function CandlestickChart({
  data,
  volumeData,
  markers,
  onMarkerClick,
  selectedTime,
  selectionStart,
  height = 400,
  formatValue,
  overlays,
}: CandlestickChartProps) {
  const onMarkerClickRef = useRef(onMarkerClick)
  onMarkerClickRef.current = onMarkerClick
  const containerRef = useRef<HTMLDivElement>(null)
  const shadeRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null)

  // Create chart once
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
      opts.localization = {
        priceFormatter: formatValue,
      }
    }

    const chart = createChart(container, opts)
    chartRef.current = chart

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
      priceFormat: formatValue
        ? { type: "custom", formatter: formatValue }
        : { type: "price", precision: 0, minMove: 1 },
    })
    candleSeriesRef.current = candleSeries

    // Volume histogram on separate price scale (bottom 20%)
    const volSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    })
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })
    volumeSeriesRef.current = volSeries

    // 특징일 마커 클릭 → 가장 가까운 마커 시각 콜백
    chart.subscribeClick((param) => {
      if (!param.time || !param.seriesData.has(candleSeries) || !onMarkerClickRef.current) return
      const t = param.time
      const day = typeof t === 'object' ? `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}` : typeof t === 'number' ? new Date(t * 1000).toISOString().slice(0, 10) : t
      onMarkerClickRef.current(day)
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
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
    }
  }, [height]) // eslint-disable-line react-hooks/exhaustive-deps

  // Update candlestick data
  useEffect(() => {
    if (!candleSeriesRef.current) return
    candleSeriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [data])

  // 특징일 마커 — 상승=아래 빨강 화살표, 하락=위 파랑 화살표
  useEffect(() => {
    if (!candleSeriesRef.current) return
    const ms = (markers ?? []).map((m) => ({
      time: m.time,
      position: m.direction === "up" ? "belowBar" as const : "aboveBar" as const,
      color: m.direction === "up" ? UP_COLOR : DOWN_COLOR,
      shape: m.direction === "up" ? "arrowUp" as const : "arrowDown" as const,
      text: m.text,
    }))
    const selection = selectedTime && data.some(d => d.time === selectedTime) ? [{ time: selectedTime, position: 'aboveBar' as const, color: '#80506f', shape: 'circle' as const, text: `선택 ${selectedTime}` }] : []
    candleSeriesRef.current.setMarkers([...ms, ...selection].sort((a, b) => a.time.localeCompare(b.time)))
  }, [markers, selectedTime, data])

  // Update volume data
  useEffect(() => {
    if (!volumeSeriesRef.current) return
    if (volumeData && volumeData.length > 0) {
      volumeSeriesRef.current.setData(volumeData)
    } else if (data.length > 0) {
      // Auto-generate volume colors from candle direction if no explicit volumeData
      // (caller should normally provide volumeData with colors)
    }
  }, [volumeData, data])

  // Optional analysis overlays share the candle price scale; existing consumers are unchanged.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !containerRef.current) return
    const theme = getComputedStyle(containerRef.current)
    const series = (overlays ?? []).filter(overlay => overlay.data.length > 0).map(overlay => {
      const line = chart.addLineSeries({
        title: overlay.title,
        color: theme.getPropertyValue(overlay.token).trim() || theme.getPropertyValue('--foreground').trim(),
        lineWidth: 2,
        lineStyle: overlay.dashed ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
      })
      line.setData(overlay.data)
      return line
    })
    return () => { if (chartRef.current === chart) series.forEach(line => chart.removeSeries(line)) }
  }, [overlays, height])

  useEffect(() => {
    const chart = chartRef.current, shade = shadeRef.current, container = containerRef.current
    if (!chart || !shade || !container) return
    const sync = () => {
      if (!selectedTime || !selectionStart) { shade.style.display = 'none'; return }
      const from = data.find(d => d.time >= selectionStart)?.time
      const left = from ? chart.timeScale().timeToCoordinate(from) : null
      const right = chart.timeScale().timeToCoordinate(selectedTime)
      if (left == null || right == null) { shade.style.display = 'none'; return }
      shade.style.display = 'block'
      shade.style.left = `${Math.max(0, left - 3)}px`
      shade.style.width = `${Math.max(0, Math.min(container.clientWidth, right + 3) - Math.max(0, left - 3))}px`
    }
    sync()
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync)
    const observer = new ResizeObserver(sync)
    observer.observe(container)
    return () => { observer.disconnect(); chart.timeScale().unsubscribeVisibleLogicalRangeChange(sync) }
  }, [data, selectedTime, selectionStart, height])

  return <div style={{ position: 'relative', width: '100%' }}>
    <div ref={containerRef} style={{ width: "100%", height }} />
    <div ref={shadeRef} aria-hidden="true" className="pointer-events-none absolute top-0 bottom-8 bg-primary/10" style={{ display: 'none' }} />
  </div>
}
