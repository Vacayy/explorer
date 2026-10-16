import { useEffect, useRef, useState } from 'react'
import { ColorType, createChart, LineStyle } from 'lightweight-charts'
import { formatNumber } from '@/utils/format'

interface Props {
  points: [string, number][]
  label: string
  unit: string
  color?: string
  height?: number
  bounded?: boolean
  zero?: boolean
  // Credit and Treasury panels share this date axis without filling missing values.
  dates?: string[]
}

export function RiskTrendChart({ points, label, unit, color = '--primary', height = 220, bounded, zero, dates }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<string | null>(null)
  useEffect(() => {
    const el = container.current
    if (!el || points.length < 2) return
    const css = () => getComputedStyle(document.documentElement)
    const token = (name: string) => css().getPropertyValue(name).trim()
    const chart = createChart(el, {
      width: el.clientWidth, height,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: token('--muted-foreground'), fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: token('--border') } },
      rightPriceScale: { borderVisible: false, minimumWidth: dates ? 88 : 62, entireTextOnly: true, ...(bounded ? { scaleMargins: { top: 0.05, bottom: 0.05 } } : {}) },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true, minBarSpacing: 0.001 },
      handleScroll: false, handleScale: false,
      localization: { locale: 'ko-KR', priceFormatter: (v: number) => `${formatNumber(Math.round(v * 100) / 100)} ${unit}` },
    })
    const series = chart.addLineSeries({
      color: token(color), lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      priceFormat: { type: 'custom', formatter: (v: number) => formatNumber(Math.round(v * 100) / 100) },
      ...(bounded ? { autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) } : zero ? { autoscaleInfoProvider: (base: () => { priceRange: { minValue: number; maxValue: number } } | null) => { const info = base(); return info ? { ...info, priceRange: { minValue: Math.min(0, info.priceRange.minValue), maxValue: Math.max(0, info.priceRange.maxValue) } } : null } } : {}),
    })
    const values = new Map(points)
    series.setData((dates ?? points.map(([d]) => d)).map(time => {
      const value = values.get(time)
      return value === undefined ? { time } : { time, value }
    }))
    if (zero || bounded) series.createPriceLine({ price: bounded ? 50 : 0, color: token('--muted-foreground'), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false })
    chart.timeScale().fitContent()
    chart.subscribeCrosshairMove(param => {
      const value = param.seriesData.get(series)
      setHover(param.time && value && 'value' in value ? `${typeof param.time === 'object' ? `${param.time.year}-${String(param.time.month).padStart(2, '0')}-${String(param.time.day).padStart(2, '0')}` : String(param.time)} · ${formatNumber(value.value)} ${unit}` : null)
    })
    const resize = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width
      if (width > 0) { chart.applyOptions({ width }); chart.timeScale().fitContent() }
    })
    resize.observe(el)
    const theme = new MutationObserver(() => {
      chart.applyOptions({ layout: { textColor: token('--muted-foreground') }, grid: { horzLines: { color: token('--border') } } })
      series.applyOptions({ color: token(color) })
    })
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] })
    return () => { resize.disconnect(); theme.disconnect(); chart.remove() }
  }, [points, dates, color, height, bounded, zero, unit])

  if (points.length < 2) return <div className="flex items-center justify-center rounded-xl bg-muted/30 text-sm text-muted-foreground" style={{ height }}>
    {points.length ? '추이를 그리려면 관측이 2개 이상 필요합니다.' : '수집된 추이 데이터가 없습니다.'}
  </div>
  return <div className="min-w-0">
    <div ref={container} role="img" aria-label={`${label}: ${points[0][0]}부터 ${points.at(-1)![0]}까지 ${points.length}개 관측, 마지막 ${formatNumber(points.at(-1)![1])} ${unit}`} />
    <p className="min-h-5 text-caption text-muted-foreground tabular-nums">{hover ?? `${points[0][0]} → ${points.at(-1)![0]} · ${formatNumber(points.length)}개 관측`}</p>
  </div>
}
