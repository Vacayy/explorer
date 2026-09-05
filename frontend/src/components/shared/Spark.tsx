/**
 * 연속값 추이 미니 라인 — 지수·가격 추이(Spark의 바 차트는 카운트용, 이건 연속값용).
 * 색은 구간 전체 방향(첫 값 대비 마지막 값): 상승=빨강·하락=파랑 (한국 컨벤션).
 */
export function SparkLine({ data, height = 26 }: { data: number[]; height?: number }) {
  if (data.length < 2) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const w = 100 // viewBox 폭 — preserveAspectRatio=none으로 컨테이너에 늘림
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w
      const y = height - 1 - ((v - min) / span) * (height - 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const up = data[data.length - 1] >= data[0]
  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      height={height}
      preserveAspectRatio="none"
      className="w-full"
      aria-hidden
    >
      <polyline
        points={pts}
        fill="none"
        stroke={up ? "var(--color-up)" : "var(--color-down)"}
        strokeWidth={1.25}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

/** 14일 언급 미니 바 차트 — 마지막 7일 강조 (탐색 모멘텀·종목 홈 신호에서 공용) */
export function Spark({ data }: { data: number[] }) {
  const max = Math.max(...data, 1)
  const w = 3, gap = 1
  return (
    <svg width={data.length * (w + gap)} height={14} className="shrink-0 opacity-80">
      {data.map((v, i) => {
        const h = Math.max(1, Math.round((v / max) * 13))
        return <rect key={i} x={i * (w + gap)} y={14 - h} width={w} height={h} rx={0.5}
          className={i >= data.length - 7 ? "fill-primary" : "fill-muted-foreground/40"} />
      })}
    </svg>
  )
}
