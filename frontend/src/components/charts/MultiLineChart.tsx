import { useRef, useEffect } from "react"
import { createChart, ColorType, LineStyle } from "lightweight-charts"
import type { IChartApi, ISeriesApi, DeepPartial, ChartOptions } from "lightweight-charts"
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
}

export default function MultiLineChart({
  data,
  lines,
  height = 350,
  formatValue,
}: MultiLineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesMapRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map())

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
    </div>
  )
}

export type { LineConfig, MultiLineChartProps }
