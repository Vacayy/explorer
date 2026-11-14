import type { CallMomentum, CallMomentumCandidate, CoreReason, SeasonCalendarDay, SeasonItem, SeasonOverview, SeasonSectorRow } from "@/types"
import { formatPercent } from "@/utils/format"

/**
 * 탐색 › 컨콜 › 실적 시즌 개요(ia-redesign §4.6a)의 순수 계산 — 캘린더 막대, 섹터 점 띠·정렬,
 * 반응 보드 탭, 새 모멘텀 묶음(새로 붙은 · 이어지는), 핵심 종목 진행판 타일 순서.
 */

const iso = (t: number) => new Date(t).toISOString().slice(0, 10)
const utc = (d: string) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10))
const weekday = (d: string) => new Date(utc(d)).getUTCDay()   // 0 = 일

/* ---------- 발표 캘린더 ---------- */

export type CalendarBar = SeasonCalendarDay & { estimated: number }

/** 시즌 첫 발표일~마지막 발표일의 거래일(주말 제외)마다 막대 하나. 주말 발표가 있으면 그날도 넣는다 */
export function calendarBars(calendar: SeasonCalendarDay[]): CalendarBar[] {
  if (!calendar.length) return []
  const byDate = new Map(calendar.map(d => [d.date, d]))
  const first = calendar[0].date, last = calendar[calendar.length - 1].date
  const out: CalendarBar[] = []
  for (let t = utc(first); t <= utc(last); t += 86_400_000) {
    const date = iso(t)
    const d = byDate.get(date)
    const wd = weekday(date)
    if (!d && (wd === 0 || wd === 6)) continue
    const day = d ?? { date, total: 0, core: 0, confirmed: 0, tickers: [] }
    out.push({ ...day, estimated: day.total - day.confirmed })
  }
  return out
}

/** 오늘이 든 주(월~일) */
export function weekOf(today: string): { start: string; end: string } {
  const wd = weekday(today)
  const start = utc(today) - ((wd + 6) % 7) * 86_400_000
  return { start: iso(start), end: iso(start + 6 * 86_400_000) }
}

/** 머리 오른쪽 요약 — 이번 주 남은 발표(오늘 포함)·그중 핵심, 가장 많은 날, 마지막 발표일 */
export function calendarSummary(calendar: SeasonCalendarDay[], today: string) {
  const w = weekOf(today)
  const left = calendar.filter(d => d.date >= today && d.date <= w.end)
  const peak = calendar.reduce<SeasonCalendarDay | null>((m, d) => (!m || d.total > m.total ? d : m), null)
  return {
    weekLeft: left.reduce((n, d) => n + d.total, 0),
    weekLeftCore: left.reduce((n, d) => n + d.core, 0),
    peak,
    last: calendar.length ? calendar[calendar.length - 1].date : null,
    total: calendar.reduce((n, d) => n + d.total, 0),
  }
}

/** 기본 선택 날짜 — 오늘 발표가 있으면 오늘, 없으면 오늘 뒤 가장 가까운 발표일, 그것도 없으면 마지막 발표일 */
export function defaultCalendarDay(calendar: SeasonCalendarDay[], today: string): string | null {
  if (!calendar.length) return null
  return calendar.find(d => d.date >= today)?.date ?? calendar[calendar.length - 1].date
}

/* ---------- 새 모멘텀 ---------- */

export type MomentumKind = "new" | "continuing"
export interface MomentumSet {
  seasonKey: string | null
  fresh: CallMomentumCandidate[]
  continuing: CallMomentumCandidate[]
  byTicker: Map<string, { kind: MomentumKind; c: CallMomentumCandidate }>
}

/** 고른 시즌의 모멘텀 — 응답의 이번 시즌이면 candidates(새로 붙은)·continuing, 지난 시즌이면 기록(history)의 후보 */
export function momentumFor(m: CallMomentum | undefined, seasonKey: string): MomentumSet {
  const empty: MomentumSet = { seasonKey: null, fresh: [], continuing: [], byTicker: new Map() }
  if (!m) return empty
  const cur = m.season.key === seasonKey
  const hist = cur ? null : m.history.find(h => h.key === seasonKey)
  if (!cur && !hist) return empty
  const fresh = [...(cur ? m.candidates : hist!.candidates)].sort((a, b) => b.score - a.score)
  const continuing = [...(cur ? m.continuing ?? [] : [])].sort((a, b) => b.score - a.score)
  const byTicker = new Map<string, { kind: MomentumKind; c: CallMomentumCandidate }>()
  for (const c of continuing) byTicker.set(c.ticker, { kind: "continuing", c })
  for (const c of fresh) byTicker.set(c.ticker, { kind: "new", c })
  return { seasonKey, fresh, continuing, byTicker }
}

export const raisedGuidance = (c: CallMomentumCandidate) => c.guidance.filter(g => g.direction === "raised").length

/** 수요 어조가 올랐나 */
export const toneUp = (c: CallMomentumCandidate) => c.tone != null && c.prev_tone != null && c.tone > c.prev_tone

/** 가속 근거 한 줄 — 수치(매출 성장 전→현 · 컨센서스 · 가이던스) / 원문 인용 / 가속이 없으면 올린 가이던스 항목 */
export function accelLine(c: CallMomentumCandidate): { kind: "numeric" | "quote" | "guidance" | "none"; text: string } {
  const a = c.accel
  if (a?.on && a.basis === "numeric") {
    const parts = [`매출 성장 ${formatPercent(a.g_prev)}→${formatPercent(a.g_now)}`]
    if (a.beat != null) parts.push(`컨센서스 대비 ${formatPercent(a.beat)}`)
    if (a.guidance_raised || raisedGuidance(c) > 0) parts.push("가이던스 상향")
    return { kind: "numeric", text: parts.join(" · ") }
  }
  if (a?.on && a.basis === "quote" && a.quote) return { kind: "quote", text: a.quote }
  const raised = c.guidance.filter(g => g.direction === "raised").map(g => g.metric)
  if (raised.length) return { kind: "guidance", text: `가이던스 상향 · ${[...new Set(raised)].join(" · ")}` }
  const lead = c.drivers.find(d => d.status === "new") ?? c.drivers.find(d => d.status === "accelerating")
  return lead ? { kind: "none", text: lead.magnitude ? `${lead.name} · ${lead.magnitude}` : lead.name } : { kind: "none", text: "" }
}

/* ---------- 이번 시즌 시장이 따진 것 ---------- */

export const DOT_RANGE = 25

/** 섹터 점 띠 — 발표한 종목의 첫 거래일 업종 대비 %p. 눈금은 ±25 고정, 넘는 값은 끝에 붙인다(실제 값은 v) */
export function sectorDots(reported: SeasonItem[], sector: string) {
  return reported.filter(i => i.sector === sector && i.d1 != null)
    .map(i => ({ ticker: i.ticker, v: i.d1 as number, x: (Math.max(-DOT_RANGE, Math.min(DOT_RANGE, i.d1 as number)) + DOT_RANGE) / (2 * DOT_RANGE) }))
    .sort((a, b) => a.v - b.v)
}

const median = (xs: number[]) => {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b), m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

export type SectorSort = "verdict" | "worst" | "momentum"
export const SECTOR_SORTS: { value: SectorSort; label: string }[] = [
  { value: "verdict", label: "판정순" }, { value: "worst", label: "반응 나쁜 순" }, { value: "momentum", label: "모멘텀 많은 순" },
]

/** 섹터 줄 + 모멘텀 수 + 중앙 반응. 요약·밸류체인 있는 섹터(main)와 나머지(rest)로 나눈 뒤 각각 정렬 */
export function sectorRows(sectors: SeasonSectorRow[], reported: SeasonItem[], momentum: MomentumSet, sort: SectorSort) {
  const rows = sectors.map((s, i) => {
    const items = reported.filter(r => r.sector === s.key)
    return {
      ...s, order: i,
      momentum: items.filter(r => momentum.byTicker.has(r.ticker)).length,
      median: median(items.flatMap(r => (r.d1 == null ? [] : [r.d1]))),
      dots: sectorDots(reported, s.key),
    }
  })
  const cmp = (a: typeof rows[number], b: typeof rows[number]) =>
    sort === "worst" ? (a.median ?? Infinity) - (b.median ?? Infinity) || a.order - b.order
      : sort === "momentum" ? b.momentum - a.momentum || a.order - b.order
        : a.order - b.order
  const main = rows.filter(r => r.dc_chain || r.verdict).sort(cmp)
  const rest = rows.filter(r => !r.dc_chain && !r.verdict).sort(cmp)
  return { main, rest }
}

/* ---------- 반응 보드 ---------- */

export type ReactionTab = "good" | "opposite" | "reversed"

/** 탭 셋 — 좋았다(첫 거래일 업종보다 강함) · 숫자와 반대로(하회에도 강세 + 상회에도 약세) · 뒤집혔다(반전·되돌림) */
export function reactionLists(reported: SeasonItem[]): Record<ReactionTab, SeasonItem[]> {
  const good = reported.filter(i => (i.d1 ?? 0) > 0).sort((a, b) => (b.d1 ?? 0) - (a.d1 ?? 0))
  const opposite = reported.filter(i => ((i.eps_surprise ?? 0) < 0 && (i.d1 ?? 0) > 0) || ((i.eps_surprise ?? 0) > 0 && (i.d1 ?? 0) < 0))
    .sort((a, b) => Math.abs(b.d1 ?? 0) - Math.abs(a.d1 ?? 0))
  const reversed = reported.filter(i => i.follow === "반전" || i.follow === "되돌림")
    .sort((a, b) => Math.abs((b.d1 ?? 0) - (b.latest ?? 0)) - Math.abs((a.d1 ?? 0) - (a.latest ?? 0)))
  return { good, opposite, reversed }
}

/* ---------- 핵심 종목 진행판 ---------- */

export type CoreTile =
  | { ticker: string; name: string | null; reasons: CoreReason[]; state: "upcoming"; date: string; momentum: boolean }
  | { ticker: string; name: string | null; reasons: CoreReason[]; state: "reported"; d1: number | null; transcriptId: number | null; momentum: boolean }
  | { ticker: string; name: string | null; reasons: CoreReason[]; state: "waiting"; date: string; momentum: boolean }
  | { ticker: string; name: string | null; reasons: CoreReason[]; state: "none"; momentum: boolean }

/** 타일 순서: 곧 발표(날짜순) → 발표 완료(첫 거래일 높은 순, 반응 대기는 뒤) → 일정 미정.
 * 예정일이 지났는데 확정·반응이 없으면 '반응 대기'로 발표 완료 묶음 끝에 둔다. */
export function coreTiles(core: SeasonOverview["core"], reported: SeasonItem[], calendar: SeasonCalendarDay[], today: string, momentum: MomentumSet): CoreTile[] {
  const rep = new Map(reported.map(r => [r.ticker, r]))
  const dateOf = new Map<string, string>()
  for (const d of calendar) for (const t of d.tickers) if (!dateOf.has(t)) dateOf.set(t, d.date)
  const tiles: CoreTile[] = core.tickers.map(t => {
    const base = { ticker: t.ticker, name: t.name, reasons: t.reasons, momentum: momentum.byTicker.has(t.ticker) }
    const r = rep.get(t.ticker)
    if (r) return { ...base, state: "reported", d1: r.d1 ?? null, transcriptId: r.transcript_id }
    const date = dateOf.get(t.ticker)
    if (date) return date >= today ? { ...base, state: "upcoming", date } : { ...base, state: "waiting", date }
    return { ...base, state: "none" }
  })
  const rank = (t: CoreTile) => t.state === "upcoming" ? 0 : t.state === "reported" ? (t.d1 == null ? 2 : 1) : t.state === "waiting" ? 2 : 3
  return tiles.sort((a, b) => rank(a) - rank(b)
    || (a.state === "upcoming" && b.state === "upcoming" ? a.date.localeCompare(b.date) : 0)
    || (a.state === "reported" && b.state === "reported" ? (b.d1 ?? -Infinity) - (a.d1 ?? -Infinity) : 0)
    || a.ticker.localeCompare(b.ticker))
}

export function coreCounts(tiles: CoreTile[]) {
  return {
    reported: tiles.filter(t => t.state === "reported" || t.state === "waiting").length,
    upcoming: tiles.filter(t => t.state === "upcoming").length,
    none: tiles.filter(t => t.state === "none").length,
  }
}

/* ---------- 시즌 선택기 ---------- */

/** 오늘이 든 실적 시즌 키 — 분기가 끝난 다음 달부터 그 분기 시즌(10~12월 = 3분기, 1~3월 = 지난해 4분기). 백엔드 call_momentum.season과 같은 규칙 */
export function currentSeasonKey(today: string): string {
  const y = +today.slice(0, 4), q = Math.floor((+today.slice(5, 7) - 1) / 3)
  return q === 0 ? `${y - 1}Q4` : `${y}Q${q}`
}

/** 시즌 목록에서 이전·다음 — windows는 첫 발표일 순 */
export function seasonNeighbors(keys: string[], current: string): { prev: string | null; next: string | null } {
  const i = keys.indexOf(current)
  if (i < 0) return { prev: null, next: null }
  return { prev: i > 0 ? keys[i - 1] : null, next: i < keys.length - 1 ? keys[i + 1] : null }
}
