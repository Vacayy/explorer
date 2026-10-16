import type { FinancialResponse } from '@/types'

export function shiftDay(day: string, amount: number) {
  const d = new Date(`${day}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + amount)
  return d.toISOString().slice(0, 10)
}
export function validDay(day: string) {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(day) &&
    Number.isFinite(Date.parse(day)) &&
    new Date(day).toISOString().slice(0, 10) === day
  )
}
function amount(value: string | null | undefined) {
  if (value == null || !value.trim()) return null
  const parsed = Number(value.replaceAll(',', ''))
  return Number.isFinite(parsed) ? parsed : null
}
export function quarterRows(data?: FinancialResponse) {
  if (!data?.periods.length) return []
  const account = (names: string[]) =>
    data.rows.find((r) => names.includes(r.account_nm))
  const revenue = account(['매출액', '영업수익', '수익(매출액)'])
  const profit = account(['영업이익', '영업이익(손실)'])
  const byPeriod = new Map(
    data.periods.map((period, i) => {
      const rev = amount(revenue?.values[i]),
        op = amount(profit?.values[i])
      return [
        period,
        {
          period,
          revenue: rev,
          profit: op,
          margin:
            rev != null && rev > 0 && op != null ? (op / rev) * 100 : null,
        },
      ]
    }),
  )
  // Preserve missing calendar quarters as gaps, rather than joining across absent reports.
  const indices = data.periods
    .filter((p) => /^\d{2}\.(03|06|09|12)$/.test(p))
    .map((p) => Number(p.slice(0, 2)) * 4 + Number(p.slice(3)) / 3 - 1)
  if (!indices.length) return [...byPeriod.values()]
  const first = Math.min(...indices),
    last = Math.max(...indices)
  return Array.from({ length: last - first + 1 }, (_, i) => {
    const n = first + i
    const period = `${String(Math.floor(n / 4)).padStart(2, '0')}.${String(((n % 4) + 1) * 3).padStart(2, '0')}`
    return (
      byPeriod.get(period) || {
        period,
        revenue: null,
        profit: null,
        margin: null,
      }
    )
  })
}
