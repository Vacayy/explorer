import type { KrAnnouncement, KrSeasonOverview } from "@/types"

/**
 * 탐색 › 컨콜 › 실적 시즌 · 한국(ia-redesign §4.22)의 순수 계산 — 캘린더 막대, 반응이 좋았던·나빴던 발표, 최근 발표 표 필터.
 * 화면(components/follow/season/KrSeasonView)과 테스트가 같이 쓴다.
 */

/** 반응 목록에 올리는 최소 시총 — 1조 */
export const BIG_CAP = 1e12

const iso = (t: number) => new Date(t).toISOString().slice(0, 10)
const utc = (d: string) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10))
const weekday = (d: string) => new Date(utc(d)).getUTCDay()

/** 막대 하나 = 하루. total = 잠정실적 공시 수, quarterly = 잠정실적 없이 분기보고서만 낸 회사 수(D-305) */
export interface KrBar { date: string; total: number; quarterly: number }

/** 시즌 결산에 맞는 정기보고서 이름 — 1·3분기 분기보고서, 2분기 반기보고서, 4분기 사업보고서 */
export function periodicReportName(seasonKey: string): string {
  const q = seasonKey.slice(-1)
  return q === "2" ? "반기보고서" : q === "4" ? "사업보고서" : "분기보고서"
}

/** 시즌 시작~(분기보고서 마감과 마지막 공시일 중 늦은 날)의 평일마다 막대 하나. 주말 공시가 있으면 그날도 넣는다 */
export function krCalendarBars(d: Pick<KrSeasonOverview, "calendar" | "season" | "deadline">): KrBar[] {
  const byDate = new Map(d.calendar.map((c) => [c.date, c]))
  const last = d.calendar.length ? d.calendar[d.calendar.length - 1].date : d.season.start
  const first = d.calendar.length && d.calendar[0].date < d.season.start ? d.calendar[0].date : d.season.start
  const end = last > d.deadline ? last : d.deadline
  const out: KrBar[] = []
  for (let t = utc(first); t <= utc(end); t += 86_400_000) {
    const date = iso(t)
    const total = byDate.get(date)?.total ?? 0
    const quarterly = byDate.get(date)?.quarterly ?? 0
    const wd = weekday(date)
    if (!total && !quarterly && (wd === 0 || wd === 6)) continue
    out.push({ date, total, quarterly })
  }
  return out
}

/** 하루 최다 잠정실적 공시일 */
export function krPeak(calendar: KrSeasonOverview["calendar"]) {
  return calendar.reduce<KrSeasonOverview["calendar"][number] | null>((m, c) => (!m || c.total > m.total ? c : m), null)
}

/** 반응이 좋았던·나빴던 발표 — 시총 1조 이상, 업종 대비 첫 반응 순으로 각 n개(좋았다 = 업종보다 오름, 나빴다 = 업종보다 내림) */
export function reactionExtremes(anns: KrAnnouncement[], n = 6): { good: KrAnnouncement[]; bad: KrAnnouncement[] } {
  const big = anns.filter((a) => (a.market_cap ?? 0) >= BIG_CAP && a.x1 != null)
  return {
    good: big.filter((a) => (a.x1 as number) > 0).sort((a, b) => (b.x1 as number) - (a.x1 as number)).slice(0, n),
    bad: big.filter((a) => (a.x1 as number) < 0).sort((a, b) => (a.x1 as number) - (b.x1 as number)).slice(0, n),
  }
}

export type KrFilter = "all" | "big" | "mine"

/** 최근 발표 표 — 필터(전체·시총 1조+·내 종목)와 캘린더에서 고른 날 */
export function filterAnnouncements(anns: KrAnnouncement[], filter: KrFilter, mine: Set<string>, day: string | null = null) {
  return anns.filter((a) => (!day || a.rcept_dt === day)
    && (filter === "all" || (filter === "big" ? (a.market_cap ?? 0) >= BIG_CAP : !!a.stock_code && mine.has(a.stock_code))))
}

export function filterCounts(anns: KrAnnouncement[], mine: Set<string>, day: string | null = null): Record<KrFilter, number> {
  return {
    all: filterAnnouncements(anns, "all", mine, day).length,
    big: filterAnnouncements(anns, "big", mine, day).length,
    mine: filterAnnouncements(anns, "mine", mine, day).length,
  }
}
