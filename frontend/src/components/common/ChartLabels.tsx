/**
 * Custom Recharts label renderers for data labels on bars and lines.
 * Supports sparse rendering to avoid overlap on dense charts.
 */

interface LabelProps {
  x?: number
  y?: number
  width?: number
  index?: number
  value?: number | string | null
}

/**
 * Data label on a line point — shows percentage.
 * Only renders every Nth point when data is dense.
 */
export function PercentLabel({ x = 0, y = 0, index = 0, value }: LabelProps & { totalPoints?: number }) {
  if (value === null || value === undefined) return null
  const num = typeof value === "string" ? parseFloat(value) : value
  if (isNaN(num)) return null
  return (
    <text x={x} y={y - 10} textAnchor="middle" fontSize={10} fontWeight={600} fill="#6b7280">
      {num.toFixed(1)}%
    </text>
  )
}

/**
 * Sparse percent label — only shows on annual or every 4th point.
 * Use this for quarterly charts to avoid clutter.
 */
export function SparsePercentLabel({ x = 0, y = 0, index = 0, value }: LabelProps) {
  if (value === null || value === undefined) return null
  // Show label on Q4 (every 4th point) or first/last
  if (index % 4 !== 3 && index !== 0) return null
  const num = typeof value === "string" ? parseFloat(value) : value
  if (isNaN(num)) return null
  return (
    <text x={x} y={y - 10} textAnchor="middle" fontSize={9} fontWeight={600} fill="#6b7280">
      {num.toFixed(1)}%
    </text>
  )
}

/** Bar label — shows value in Korean locale above each bar */
export function EokLabel({ x = 0, y = 0, width = 0, value }: LabelProps) {
  if (!value) return null
  const num = typeof value === "number" ? value : parseFloat(String(value))
  if (isNaN(num) || num === 0) return null
  return (
    <text x={x + width / 2} y={y - 5} textAnchor="middle" fontSize={9} fontWeight={500} fill="#374151">
      {num.toLocaleString("ko-KR")}
    </text>
  )
}

/** Sparse bar label — only shows every Nth bar */
export function SparseEokLabel({ x = 0, y = 0, width = 0, index = 0, value }: LabelProps) {
  if (!value || index % 4 !== 3) return null
  const num = typeof value === "number" ? value : parseFloat(String(value))
  if (isNaN(num) || num === 0) return null
  return (
    <text x={x + width / 2} y={y - 5} textAnchor="middle" fontSize={8} fontWeight={500} fill="#374151">
      {num.toLocaleString("ko-KR")}
    </text>
  )
}
