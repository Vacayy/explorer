import type { CreditRow } from '@/types'

/** 기본 선택 — 1개월 확대 폭 상위 n곳. 1개월 변화가 비어 있으면(이력 축적 전) 스프레드 넓은 순으로 대신한다(§4.8c) */
export function defaultCreditPicks(rows: readonly CreditRow[], n = 2): string[] {
  const priced = rows.filter(r => r.spread_bp != null)
  const widening = priced.filter(r => r.chg_1m != null).sort((a, b) => b.chg_1m! - a.chg_1m!)
  const pool = widening.length >= n ? widening : [...widening, ...priced.filter(r => r.chg_1m == null).sort((a, b) => b.spread_bp! - a.spread_bp!)]
  return pool.slice(0, n).map(r => r.ticker)
}

export const bySpread = (a: CreditRow, b: CreditRow) => (b.spread_bp ?? -Infinity) - (a.spread_bp ?? -Infinity)

/** 그룹별 중앙값 — 그룹 순서는 서버 순서(자금 흐름) 그대로. 스프레드가 없는 채권은 중앙값에서 빼고 채권 수에는 센다 */
export function creditGroupMedians(rows: readonly CreditRow[], groups: readonly { key: string; label: string }[]) {
  return groups.map(g => {
    const items = rows.filter(r => r.group === g.key)
    const s = items.map(r => r.spread_bp).filter((v): v is number => v != null).sort((a, b) => a - b)
    const m = Math.floor(s.length / 2)
    const median = !s.length ? null : s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
    return { key: g.key, label: g.label, median, count: items.length, hy: items.filter(r => r.hy).length }
  })
}

export type CreditRange = '3m' | '1y' | 'all'
export const parseCreditRange = (v: string | null): CreditRange => v === '3m' || v === 'all' ? v : '1y'

/** 기간 자르기 — 마지막 관측일에서 3개월·1년 전까지 */
export function sliceByRange<T extends { date: string }>(points: readonly T[], range: CreditRange): T[] {
  if (range === 'all' || !points.length) return [...points]
  const last = new Date(`${points[points.length - 1].date}T00:00:00Z`)
  last.setUTCMonth(last.getUTCMonth() - (range === '3m' ? 3 : 12))
  const from = last.toISOString().slice(0, 10)
  return points.filter(p => p.date >= from)
}
