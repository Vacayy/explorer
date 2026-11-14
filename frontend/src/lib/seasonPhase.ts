import type { SeasonWindow } from "@/types"

/**
 * 미국 실적 시즌 판정 (ia-redesign §4.28) — 오늘이 어떤 시즌의 첫 발표일~마지막 발표일 안에 있으면 '시즌 중',
 * 어디에도 없으면 '시즌 사이'. 시즌 사이에는 다음 시즌(첫 발표일이 오늘 뒤인 가장 가까운 시즌)까지 D-n과
 * 지난 시즌(마지막 발표일이 오늘 앞인 가장 늦은 시즌)을 돌려준다. '막바지' 구분은 두지 않는다(11-04 결정).
 */
export type SeasonPhase =
  | { state: "in"; current: SeasonWindow }
  | { state: "between"; next: SeasonWindow | null; last: SeasonWindow | null; daysToNext: number | null }

/** 'YYYY-MM-DD' 두 날짜 사이 일수(b − a) — 시간대와 무관하게 날짜만 센다 */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10)) - Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))) / 86_400_000)
}

export function seasonPhase(today: string, windows: SeasonWindow[]): SeasonPhase {
  const current = windows.find(w => w.first <= today && today <= w.last)
  if (current) return { state: "in", current }
  const next = windows.filter(w => w.first > today).sort((a, b) => a.first.localeCompare(b.first))[0] ?? null
  const last = windows.filter(w => w.last < today).sort((a, b) => b.last.localeCompare(a.last))[0] ?? null
  return { state: "between", next, last, daysToNext: next ? daysBetween(today, next.first) : null }
}

/** 오늘 날짜(로컬) 'YYYY-MM-DD' */
export function localToday(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

/** 곧 발표 목록을 날짜별로 묶는다 — 날짜순, 같은 날 안은 들어온 순서. 한 날짜라도 확정이 아니면 예상일로 본다 */
export function groupByDate<T extends { event_date: string; confirmed: boolean }>(items: T[]): { date: string; items: T[]; estimated: boolean }[] {
  const out = new Map<string, T[]>()
  for (const it of [...items].sort((a, b) => a.event_date.localeCompare(b.event_date))) {
    out.set(it.event_date, [...(out.get(it.event_date) ?? []), it])
  }
  return [...out].map(([date, rows]) => ({ date, items: rows, estimated: rows.some(r => !r.confirmed) }))
}
