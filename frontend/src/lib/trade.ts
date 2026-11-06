import type { TradeFollowRow } from '@/types'
import { localToday } from "@/lib/seasonPhase"

/** 주요 품목 한눈에 — 정렬 (URL trade_sort). 옛 값(contribution·group)은 기본으로 */
export type TradeGridSort = 'value' | 'surge' | 'mine'
export const parseTradeGridSort = (v: string | null): TradeGridSort => v === 'surge' || v === 'mine' ? v : 'value'

/**
 * 격자에 올릴 품목 — 상위 품목(다른 팔로우 품목의 세목이 아닌 것)만, 최신 수출액이 있는 것.
 * value = 수출액 순 · surge = 급등 먼저(신규는 급등 아님, D-303), 그 안은 수출액 순 · mine = 내 종목과 이어진 품목 먼저.
 */
export function rankTradeGrid(follows: readonly TradeFollowRow[], sort: TradeGridSort, mine: ReadonlySet<string> = new Set(), n = 12): TradeFollowRow[] {
  const pool = follows.filter(f => !f.nested_in && f.latest_export != null)
  const surge = (f: TradeFollowRow) => f.flag === 'surge' ? 1 : 0
  const first = (f: TradeFollowRow) => sort === 'surge' ? surge(f) : sort === 'mine' ? (mine.has(f.hs_code) ? 1 : 0) : 0
  return [...pool].sort((a, b) => first(b) - first(a) || b.latest_export! - a.latest_export!).slice(0, n)
}

/** 12개월 이동평균 — 앞 11달은 null */
export function movingAverage(values: readonly (number | null)[], window = 12): (number | null)[] {
  return values.map((_, i) => {
    if (i < window - 1) return null
    const slice = values.slice(i - window + 1, i + 1)
    return slice.some(v => v == null) ? null : (slice as number[]).reduce((a, b) => a + b, 0) / window
  })
}

/** 'YYYY-MM' → '2026년 9월' */
export const monthLabel = (period: string | null) => period ? `${period.slice(0, 4)}년 ${+period.slice(5, 7)}월` : '-'

/** 통계월이 지난달보다 오래됐나 — 관세청 품목별 통계는 매월 중순에 나와서, 그 전에는 지지난달 값을 보인다(§4.28 부분) */
export function tradeIsLagging(period: string | null, today: string = localToday()): boolean {
  if (!period) return false
  const y = +today.slice(0, 4), m = +today.slice(5, 7)
  const prev = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`
  return period < prev
}
