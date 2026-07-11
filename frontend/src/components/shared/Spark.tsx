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
