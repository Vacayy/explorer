import { polyline, rebase } from "@/lib/svgLines"
import { cn } from "@/lib/utils"

/**
 * 섹터 대표지수 vs 코스피(시안 Sector-Overview ①) — 둘 다 기간 시작 = 100. 대표지수 실선(상승색) + 옅은 면, 코스피 점선.
 * SVG 하나(viewBox 1000×220, 비율 고정 안 함)라 칸을 그대로 채운다. 아래 눈금 5개(YY.MM).
 */
export function SectorIndexChart({ points, label, className }: { points: { d: string; v: number; k: number | null }[]; label: string; className?: string }) {
  const v = rebase(points.map(p => p.v))
  const kRaw = points.map(p => p.k)
  const k0 = kRaw.find(x => x != null)
  const k = kRaw.map(x => x != null && k0 ? x / k0 * 100 : null)
  const kv = k.filter((x): x is number => x != null)
  if (v.length < 2) return <div className={cn("relative pb-[18px]", className)} />
  const all = [...v, ...kv]
  const lo = Math.min(...all), hi = Math.max(...all)
  const line = polyline(v, 1000, 220, lo, hi, 10)
  // 코스피는 빈 날을 건너뛰어 잇는다(대표지수 날짜 축 그대로)
  const kLine = k.map((x, i) => x == null ? null : `${(i / (v.length - 1) * 1000).toFixed(1)},${(10 + (hi - x) / ((hi - lo) || 1) * 200).toFixed(1)}`).filter(Boolean).join(" ")
  const n = points.length
  const ticks = [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor(3 * n / 4), n - 1]
  return <div data-sector-chart className={cn("relative pb-[18px]", className)}>
    <svg viewBox="0 0 1000 220" preserveAspectRatio="none" role="img" aria-label={label} className="absolute inset-x-0 top-0 h-[calc(100%-18px)] w-full">
      <polygon points={`0,220 ${line} 1000,220`} className="fill-up-tint" />
      {kLine && <polyline points={kLine} fill="none" className="stroke-ink-3" strokeWidth="1.2" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />}
      <polyline points={line} fill="none" className="stroke-up" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
    </svg>
    {ticks.map((i, j) => <span key={`${i}-${j}`} className="absolute bottom-0 font-mono text-[10.5px] whitespace-nowrap text-ink-3"
      style={{ left: `${(i / (n - 1) * 100).toFixed(1)}%`, transform: `translateX(-${j === 0 ? 0 : j === 4 ? 100 : 50}%)` }}>{points[i].d.slice(2, 7).replace("-", ".")}</span>)}
  </div>
}

/** 기간 끝 값(시작 = 100 기준 등락 %) */
export function rangeReturns(points: { v: number; k: number | null }[]): { v: number | null; k: number | null } {
  const v = points.length > 1 ? (points[points.length - 1].v / points[0].v - 1) * 100 : null
  const ks = points.map(p => p.k).filter((x): x is number => x != null)
  return { v, k: ks.length > 1 ? (ks[ks.length - 1] / ks[0] - 1) * 100 : null }
}
