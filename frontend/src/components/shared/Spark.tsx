/**
 * 연속값 추이 미니 라인 — 지수·가격 추이(Spark의 바 차트는 카운트용, 이건 연속값용).
 * 색은 구간 전체 방향(첫 값 대비 마지막 값): 상승=--up(분홍·다크 오렌지)·하락=--down(파랑) (D-320).
 */
export function SparkLine({ data, height = 26, className = "w-full", neutral }: { data: number[]; height?: number; className?: string; /** 회색 선 — 값의 좋고 나쁨이 방향과 무관한 지표(금리·스프레드·VIX) */ neutral?: boolean }) {
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
      className={className}
      aria-hidden
    >
      <polyline
        points={pts}
        fill="none"
        stroke={neutral ? "var(--ink-2)" : up ? "var(--up)" : "var(--down)"}
        strokeWidth={1.25}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

/**
 * 지표 추이 — 회색 선 + 옅은 면 + 끝점(시안 Home 국면·리스크 타일). 색은 값의 좋고 나쁨을 말하지 않으므로 회색 계열만 쓴다.
 * ref: 기준선(점선, 예: VIX 20 · 공포탐욕 50) — 구간 밖이면 그리지 않는다.
 */
export function AreaSpark({ data, height = 64, refValue, label }: { data: number[]; height?: number; refValue?: number | null; label?: string }) {
  if (data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data)
  const span = max - min || 1
  const W = 300, pad = 4
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2)
  const pts = data.map((v, i) => `${((i / (data.length - 1)) * W).toFixed(1)},${y(v).toFixed(1)}`)
  const lastY = y(data[data.length - 1])
  const showRef = refValue != null && refValue > min && refValue < max
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} height={height} preserveAspectRatio="none" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}
        className="block w-full overflow-visible">
        <path d={`M0,${height} L${pts.join(" L")} L${W},${height} Z`} fill="var(--chip)" opacity={0.7} />
        {showRef && <line x1={0} x2={W} y1={y(refValue)} y2={y(refValue)} stroke="var(--line-2)" strokeWidth={1} strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />}
        <polyline points={pts.join(" ")} fill="none" stroke="var(--ink-2)" strokeWidth={1.6} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <span aria-hidden className="absolute -right-[3px] size-1.5 rounded-full bg-ink" style={{ top: `calc(${(lastY / height) * 100}% - 3px)` }} />
      {showRef && <span aria-hidden className="absolute left-0 font-mono text-[10.5px] text-ink-3 tabular-nums" style={{ top: `calc(${(y(refValue) / height) * 100}% - 15px)` }}>{refValue}</span>}
    </div>
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
