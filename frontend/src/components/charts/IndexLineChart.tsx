import { cn } from "@/lib/utils"
import { formatLevel } from "@/utils/format"

export interface IndexLinePoint {
  /** 0~1 — 가로 위치(1일은 개장~마감 시각 비율, 기간은 순번 비율) */
  x: number
  v: number
}

/**
 * 지수 선 차트(시안 Home-KR·US ①) — 등락 방향 색 선 + 같은 색 옅은 면 + 기준선(점선, 전일 종가·기간 시작 전 값) + 아래 시각 눈금.
 * SVG 하나(viewBox 1000×200, 비율 고정 안 함)라 칸 폭·높이를 그대로 채운다. 선 굵기는 화면 픽셀 고정(non-scaling-stroke).
 * dim = 개장 전 직전 거래일 경로(흐리게).
 */
export function IndexLineChart({ points, base, ticks, dim = false, className, label = "지수 추이" }: {
  points: IndexLinePoint[]
  base: number | null
  ticks: { x: number; t: string }[]
  dim?: boolean
  className?: string
  label?: string
}) {
  const vals = points.map(p => p.v).concat(base == null ? [] : [base])
  if (!points.length || !vals.length) return <div className={cn("relative pb-[18px]", className)} />
  const lo0 = Math.min(...vals), hi0 = Math.max(...vals)
  const pad = (hi0 - lo0) * 0.08 || 1
  const lo = lo0 - pad, hi = hi0 + pad
  const y = (v: number) => 8 + (hi - v) / (hi - lo) * 184
  const pts = points.map(p => `${(p.x * 1000).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ")
  const area = `${(points[0].x * 1000).toFixed(1)},200 ${pts} ${(points[points.length - 1].x * 1000).toFixed(1)},200`
  const last = points[points.length - 1].v
  const down = base != null && last < base
  const by = base == null ? null : y(base)
  return (
    <div data-index-chart className={cn("relative pb-[18px]", dim && "opacity-45", className)}>
      <svg viewBox="0 0 1000 200" preserveAspectRatio="none" role="img" aria-label={label} className="absolute inset-x-0 top-0 h-[calc(100%-18px)] w-full overflow-visible">
        <polygon points={area} className={down ? "fill-down-tint" : "fill-up-tint"} />
        {by != null && <line x1="0" x2="1000" y1={by} y2={by} className="stroke-ink-3" strokeWidth="1" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />}
        <polyline points={pts} fill="none" className={down ? "stroke-down" : "stroke-up"} strokeWidth="1.8" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      {by != null && <span className="absolute right-0 -translate-y-[120%] bg-surface px-0.5 font-mono text-[10.5px] text-ink-3 tabular-nums" style={{ top: `calc(${(by / 200 * 100).toFixed(1)}% * 0.85)` }}>기준 {formatLevel(base)}</span>}
      {ticks.map(t => <span key={`${t.t}-${t.x}`} className="absolute bottom-0 -translate-x-1/2 font-mono text-[10.5px] whitespace-nowrap text-ink-3" style={{ left: `${(t.x * 100).toFixed(1)}%` }}>{t.t}</span>)}
    </div>
  )
}
