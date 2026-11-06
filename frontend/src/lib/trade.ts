import type { TradeFlag } from '@/types'
import { localToday } from "@/lib/seasonPhase"

/** 품목 모니터 — 정렬 (URL trade_sort). 옛 값(contribution·group)은 기본으로 */
export type TradeGridSort = 'value' | 'surge' | 'mine'
export const parseTradeGridSort = (v: string | null): TradeGridSort => v === 'surge' || v === 'mine' ? v : 'value'

/** 품목 모니터 — 기간 (URL trade_period). 2년 = 24개월(기본) · 5년 = 60개월 */
export type TradePeriod = '2y' | '5y'
export const parseTradePeriod = (v: string | null): TradePeriod => v === '5y' ? '5y' : '2y'
export const TRADE_PERIOD_MONTHS: Record<TradePeriod, 24 | 60> = { '2y': 24, '5y': 60 }

interface Rankable { hs_code: string; latest_export: number | null; flag: TradeFlag | null; nested_in?: string | null }

/**
 * 벽에 올릴 품목 — 상위 품목(다른 팔로우 품목의 세목이 아닌 것)만, 최신 수출액이 있는 것.
 * value = 수출액 순 · surge = 급등 먼저(신규는 급등 아님, D-303), 그 안은 수출액 순 · mine = 내 종목과 이어진 품목 먼저.
 */
export function rankTradeGrid<T extends Rankable>(items: readonly T[], sort: TradeGridSort, mine: ReadonlySet<string> = new Set(), n = Infinity): T[] {
  const pool = items.filter(f => !f.nested_in && f.latest_export != null)
  const surge = (f: T) => f.flag === 'surge' ? 1 : 0
  const first = (f: T) => sort === 'surge' ? surge(f) : sort === 'mine' ? (mine.has(f.hs_code) ? 1 : 0) : 0
  return [...pool].sort((a, b) => first(b) - first(a) || b.latest_export! - a.latest_export!).slice(0, n)
}

/** 산업 칩 — 전체 + 산업별 품목 수(많은 순). 분류 없는 품목은 '미분류' */
export function groupChips(items: readonly { group_label: string | null }[]): { key: string; label: string }[] {
  const counts = new Map<string, number>()
  for (const i of items) counts.set(i.group_label ?? '미분류', (counts.get(i.group_label ?? '미분류') ?? 0) + 1)
  return [{ key: 'all', label: `전체 ${items.length}` },
    ...[...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ko')).map(([k, n]) => ({ key: k, label: `${k} ${n}` }))]
}

/** 카드 벽 한 쪽 — page는 1부터, 범위를 넘으면 마지막 쪽 */
export function pageOf<T>(list: readonly T[], page: number, size: number): { rows: T[]; page: number; pages: number; from: number; to: number } {
  const pages = Math.max(1, Math.ceil(list.length / size))
  const p = Math.min(Math.max(1, page || 1), pages)
  const rows = list.slice((p - 1) * size, p * size)
  return { rows, page: p, pages, from: rows.length ? (p - 1) * size + 1 : 0, to: (p - 1) * size + rows.length }
}

/** 월별 값 → 같은 달 전년 대비(%) — 12달 전 값이 없거나 0이면 null */
export function yoySeries(values: readonly (number | null)[]): (number | null)[] {
  return values.map((v, i) => {
    const base = i >= 12 ? values[i - 12] : null
    return v == null || !base ? null : (v / base - 1) * 100
  })
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
