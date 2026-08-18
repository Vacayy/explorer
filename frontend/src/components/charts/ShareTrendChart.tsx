import { useEffect, useRef, useState } from "react"

/**
 * 비중 추이 다중 라인 차트 — **의존성 없는 SVG 직접 구현** (D-114).
 *
 * lightweight-charts를 쓰지 않는 이유: (a) 7개 남짓의 스냅샷을 겹쳐 비교하는 용도에 캔들·시간축
 * 엔진은 과하고 (b) 그쪽은 CSS 변수를 못 받아 색을 하드코딩해야 해 디자인 토큰 규칙(하드코딩 hex 금지)과
 * 충돌한다. SVG는 `var(--color-chart-N)`을 그대로 받아 라이트·다크가 자동으로 맞는다.
 *
 * x축은 **날짜 간격이 아니라 인덱스 등간격**이다 — 스냅샷이 불규칙(07-30·08-02·08-06…)해서
 * 실제 간격으로 그리면 빈 구간이 넓어 모양이 안 읽힌다. 목적이 '국면의 모양'이라 등간격이 맞다.
 * y축은 0 기준이 아니라 데이터 범위 기준 — 1.8%대와 60%대를 같이 담으면 작은 쪽이 짜부라진다.
 */
export interface SeriesPoint { label: string; value: number }
export interface TrendSeries { name: string; color: string; points: SeriesPoint[] }

const PAD = { top: 10, right: 10, bottom: 18, left: 32 }
const Y_TICKS = 3
const X_LABELS = 4

export function ShareTrendChart({
  series, height = 168, unit = "%", labelFormat = (s: string) => s.slice(5),
}: {
  series: TrendSeries[]
  height?: number
  unit?: string
  labelFormat?: (label: string) => string
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [hover, setHover] = useState<number | null>(null)

  // 컨테이너 폭을 재서 px 좌표로 그린다 — viewBox 스트레치는 선 두께·글자를 왜곡한다
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const xLabels = series[0]?.points.map((p) => p.label) ?? []
  const n = xLabels.length
  const values = series.flatMap((s) => s.points.map((p) => p.value))
  if (n < 2 || values.length === 0) {
    return <div ref={boxRef} style={{ height }} className="grid place-items-center text-[11px] text-muted-foreground">
      추이를 그릴 스냅샷이 부족합니다
    </div>
  }

  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = hi - lo || 1
  const yMin = Math.max(0, lo - span * 0.12)
  const yMax = hi + span * 0.12
  const innerW = Math.max(0, width - PAD.left - PAD.right)
  const innerH = Math.max(0, height - PAD.top - PAD.bottom)
  const xAt = (i: number) => PAD.left + (n === 1 ? innerW / 2 : (innerW * i) / (n - 1))
  const yAt = (v: number) => PAD.top + innerH - ((v - yMin) / (yMax - yMin)) * innerH

  const yTicks = Array.from({ length: Y_TICKS }, (_, i) => yMin + ((yMax - yMin) * i) / (Y_TICKS - 1))
  const step = Math.max(1, Math.ceil(n / X_LABELS))
  const xShow = new Set<number>([0, n - 1])
  for (let i = 0; i < n; i += step) xShow.add(i)

  return (
    <div ref={boxRef} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img"
          aria-label={`섹터 비중 추이 — ${series.map((s) => s.name).join(", ")}`}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const rel = e.clientX - rect.left - PAD.left
            const i = Math.round((rel / (innerW || 1)) * (n - 1))
            setHover(Math.min(n - 1, Math.max(0, i)))
          }}>
          {/* y 그리드 + 라벨 */}
          {yTicks.map((v, i) => (
            <g key={i} className="text-border">
              <line x1={PAD.left} x2={width - PAD.right} y1={yAt(v)} y2={yAt(v)}
                stroke="currentColor" strokeWidth={1} opacity={0.5} />
              <text x={PAD.left - 5} y={yAt(v) + 3} textAnchor="end"
                className="fill-muted-foreground" fontSize={9}>
                {v.toFixed(0)}{unit}
              </text>
            </g>
          ))}

          {/* 호버 가이드 */}
          {hover !== null && (
            <line x1={xAt(hover)} x2={xAt(hover)} y1={PAD.top} y2={PAD.top + innerH}
              className="text-muted-foreground" stroke="currentColor" strokeWidth={1}
              strokeDasharray="3 3" opacity={0.6} />
          )}

          {/* 라인 + 점 */}
          {series.map((s) => {
            const d = s.points
              .map((p, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(1)},${yAt(p.value).toFixed(1)}`)
              .join(" ")
            return (
              <g key={s.name}>
                <path d={d} fill="none" stroke={s.color} strokeWidth={1.75}
                  strokeLinejoin="round" strokeLinecap="round" />
                {s.points.map((p, i) => (
                  <circle key={i} cx={xAt(i)} cy={yAt(p.value)}
                    r={hover === i ? 3 : 1.75} fill={s.color} />
                ))}
              </g>
            )
          })}

          {/* x 라벨 */}
          {[...xShow].sort((a, b) => a - b).map((i) => (
            <text key={i} x={xAt(i)} y={height - 5} fontSize={9}
              textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}
              className="fill-muted-foreground">
              {labelFormat(xLabels[i])}
            </text>
          ))}
        </svg>
      )}

      {/* 호버 값 — 차트 위 겹침 대신 아래 한 줄로 (좁은 카드에서 가림 방지) */}
      <div className="mt-0.5 h-4 text-[10px] tabular-nums text-muted-foreground">
        {hover !== null && (
          <span>
            {labelFormat(xLabels[hover])}
            {series.map((s) => (
              <span key={s.name} className="ml-2">
                <span style={{ color: s.color }}>■</span> {s.name} {s.points[hover]?.value?.toFixed(1)}{unit}
              </span>
            ))}
          </span>
        )}
      </div>
    </div>
  )
}
