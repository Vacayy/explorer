import { useRef, useEffect } from "react"
import { createChart, ColorType } from "lightweight-charts"
import type { IChartApi, ISeriesApi, DeepPartial, ChartOptions } from "lightweight-charts"
import { DEFAULT_CHART_OPTIONS } from "./LightweightChart"

interface AreaSeriesChartProps {
  data: { time: string; value: number }[]
  height?: number
  color?: string
  formatValue?: (value: number) => string
  showVolume?: boolean
  volumeData?: { time: string; value: number; color?: string }[]
}

export default function AreaSeriesChart({
  data,
  height = 350,
  color = "#3b82f6",
  formatValue,
  showVolume = false,
  volumeData,
}: AreaSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const areaSeriesRef = useRef<ISeriesApi<"Area"> | null>(null)
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
      opts.localization = { priceFormatter: formatValue }
    }

    const chart = createChart(container, opts)
    chartRef.current = chart

    const areaSeries = chart.addAreaSeries({
      lineColor: color,
      topColor: color + "4d",
      bottomColor: color + "00",
      lineWidth: 2,
      priceFormat: formatValue
        ? { type: "custom", formatter: formatValue }
        : { type: "price", precision: 0, minMove: 1 },
    })
    areaSeriesRef.current = areaSeries

    if (showVolume) {
      const volSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      })
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      })
      volumeSeriesRef.current = volSeries
    }

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
      areaSeriesRef.current = null
      volumeSeriesRef.current = null
    }
    // Recreate chart only when structural props change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, color, showVolume])

  // Update area data
  useEffect(() => {
    if (!areaSeriesRef.current || data.length === 0) return
    areaSeriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [data])

  // Update volume data
  useEffect(() => {
    if (!volumeSeriesRef.current || !volumeData || volumeData.length === 0) return
    volumeSeriesRef.current.setData(volumeData)
  }, [volumeData])

  return <div ref={containerRef} style={{ width: "100%", height }} />
}
