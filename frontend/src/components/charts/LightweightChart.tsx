import { useRef, useEffect } from "react"
import { createChart, ColorType } from "lightweight-charts"
import type { IChartApi, DeepPartial, ChartOptions } from "lightweight-charts"

interface LightweightChartProps {
  height?: number
  options?: DeepPartial<ChartOptions>
  onChart?: (chart: IChartApi) => void
}

const DEFAULT_CHART_OPTIONS: DeepPartial<ChartOptions> = {
  layout: {
    background: { type: ColorType.Solid, color: "transparent" },
    textColor: "#6b7280",
    fontFamily: "inherit",
  },
  grid: {
    vertLines: { color: "#f0f0f0" },
    horzLines: { color: "#f0f0f0" },
  },
  crosshair: {
    vertLine: { labelBackgroundColor: "#6b7280" },
    horzLine: { labelBackgroundColor: "#6b7280" },
  },
  timeScale: {
    borderColor: "#e5e7eb",
    timeVisible: false,
  },
  rightPriceScale: {
    borderColor: "#e5e7eb",
  },
}

/**
 * Generic lightweight-charts wrapper.
 * Handles chart creation, resize, and cleanup.
 * Use `onChart` callback to add series after the chart is created.
 */
export default function LightweightChart({ height = 350, options, onChart }: LightweightChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  const onChartRef = useRef(onChart)
  onChartRef.current = onChart

  const optionsRef = useRef(options)
  optionsRef.current = options

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const merged: DeepPartial<ChartOptions> = {
      ...DEFAULT_CHART_OPTIONS,
      ...optionsRef.current,
      layout: {
        ...DEFAULT_CHART_OPTIONS.layout,
        ...optionsRef.current?.layout,
      },
      width: container.clientWidth,
      height,
    }

    const chart = createChart(container, merged)
    chartRef.current = chart

    onChartRef.current?.(chart)

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect
        if (width > 0) {
          chart.applyOptions({ width })
        }
      }
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [height])

  return <div ref={containerRef} style={{ width: "100%", height }} />
}

export { DEFAULT_CHART_OPTIONS }
export type { LightweightChartProps }
