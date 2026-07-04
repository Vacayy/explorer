import { useRef, useEffect } from "react"
import { createChart, ColorType } from "lightweight-charts"
import type { IChartApi, ISeriesApi, DeepPartial, ChartOptions } from "lightweight-charts"
import { DEFAULT_CHART_OPTIONS } from "./LightweightChart"

interface CandlestickChartProps {
  data: { time: string; open: number; high: number; low: number; close: number }[]
  volumeData?: { time: string; value: number; color: string }[]
  height?: number
  formatValue?: (value: number) => string
}

// Korean stock convention: red = up, blue = down
const UP_COLOR = "#ef4444"
const DOWN_COLOR = "#3b82f6"

export default function CandlestickChart({
  data,
  volumeData,
  height = 400,
  formatValue,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
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
    if (!candleSeriesRef.current || data.length === 0) return
    candleSeriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [data])

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

  return <div ref={containerRef} style={{ width: "100%", height }} />
}
