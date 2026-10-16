/**
 * 유무증 D-day — 순수 함수 (런타임 의존 없음 — 타입만 가져온다, tests/rights-calendar.test.mjs).
 * 날짜 필드는 'YYYY-MM-DD'(국내 일정, KST). 오늘도 KST로 잡는다.
 */
import type { RightsRow } from "@/types"

export const RIGHTS_EVENTS = [
  { key: "date_ex_rights", label: "권리락" },
  { key: "date_sub_start", label: "구주주 청약" },
  { key: "date_public_start", label: "일반 공모" },
  { key: "date_rights_listing_end", label: "권리 매도 마감" },
  { key: "date_payment", label: "납입" },
  { key: "date_new_listing", label: "신주 상장" },
] as const satisfies readonly { key: keyof RightsRow; label: string }[]

export interface RightsEvent { date: string; dday: number; label: string; row: RightsRow }

/** KST 기준 오늘 'YYYY-MM-DD' */
export function kstToday(now: Date = new Date()): string {
  return new Date(now.getTime() + 9 * 3600_000).toISOString().slice(0, 10)
}

const dayNo = (ymd: string) => Date.UTC(+ymd.slice(0, 4), +ymd.slice(5, 7) - 1, +ymd.slice(8, 10)) / 86_400_000

/** 오늘부터 days일 안의 일정 — 날짜 순, 같은 날은 내 종목(보유→관심) 먼저 */
export function upcomingRightsEvents(rows: RightsRow[], today: string, days = 7): RightsEvent[] {
  const t0 = dayNo(today)
  const rank = (r: RightsRow) => r.my_group === "보유" ? 0 : r.my_group === "관심" ? 1 : 2
  const out: RightsEvent[] = []
  for (const row of rows) {
    for (const ev of RIGHTS_EVENTS) {
      const d = row[ev.key]
      if (typeof d !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(d)) continue
      const dday = dayNo(d) - t0
      if (dday >= 0 && dday <= days) out.push({ date: d, dday, label: ev.label, row })
    }
  }
  return out.sort((a, b) => a.dday - b.dday || rank(a.row) - rank(b.row))
}
