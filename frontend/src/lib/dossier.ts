/**
 * 종목 도시에(국내 /analyze/:code/*, 미국 /us/:ticker) 공용 순수 로직 — ia-redesign §4.9·§4.13.
 * 화면 머리 가격은 차트와 같은 저장 시세(국내 stock_prices · 미국 us_prices)의 마지막 종가로 맞춘다(§8.8 가격 기준 통일).
 */
import type { StockPriceItem } from '@/types'

export interface LastClose {
  close: number
  date: string            // YYYY-MM-DD
  changePct: number | null
}

/** 저장 시세의 마지막 종가와 전일 대비 — 종가가 빈 봉은 건너뛴다 */
export function lastClose(prices: readonly StockPriceItem[] | undefined): LastClose | null {
  const rows = (prices ?? []).filter((p) => p.close != null && p.close > 0)
  const last = rows.at(-1)
  if (!last) return null
  const prev = rows.at(-2)?.close ?? null
  return {
    close: last.close!,
    date: last.trade_date.slice(0, 10),
    changePct: prev ? ((last.close! - prev) / prev) * 100 : null,
  }
}

/** '2026-11-03' → '11/3' */
export const shortDate = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`

/** 목표가 여력(%) — 현재가·목표가 중 하나라도 없으면 null */
export function upside(target: number | null | undefined, price: number | null | undefined): number | null {
  return target && price ? ((target - price) / price) * 100 : null
}

export type DisclosureTag = '주주환원' | '실적' | '지분'
const TAGS: [DisclosureTag, RegExp][] = [
  ['주주환원', /자기주식|자사주|배당|주식\s*소각|소각\s*결정/],
  ['실적', /잠정\)?실적|영업\(잠정\)|실적\s*등에\s*대한|매출액또는손익구조|손익구조|(분|반)기보고서|사업보고서/],
  ['지분', /대량보유|임원ㆍ?주요주주|임원·주요주주|최대주주/],
]

/** 국내 개요 › 기업활동의 '최근 14일' 칸에 올릴 공시 — 주주환원·실적·대량보유/임원 지분만(같은 목록 칸). 나머지는 null */
export function disclosureTag(reportNm: string | null | undefined): DisclosureTag | null {
  const name = reportNm ?? ''
  for (const [tag, re] of TAGS) if (re.test(name)) return tag
  return null
}

/** 미국 도시에 탭 — URL ?tab= 이 유일한 상태. 옛 'analysis'(렌즈·월드모델)는 'lens'로 */
export const US_TABS = [
  { key: 'overview', label: '개요' },
  { key: 'financials', label: '실적·사업' },
  { key: 'evidence', label: '자료' },
  { key: 'lens', label: '투자 렌즈' },
] as const
export type UsTab = (typeof US_TABS)[number]['key']

export function usTabOf(search: string): UsTab {
  const t = new URLSearchParams(search).get('tab')
  if (t === 'analysis') return 'lens'
  return US_TABS.some((x) => x.key === t) ? (t as UsTab) : 'overview'
}

export const usTabPath = (ticker: string, key: UsTab) => `/us/${ticker}${key === 'overview' ? '' : `?tab=${key}`}`

/** 국내 실적 탭 표시 구간 ?n=4|8|12 (기본 8) */
export function quarterCount(raw: string | null): 4 | 8 | 12 {
  return raw === '4' ? 4 : raw === '12' ? 12 : 8
}

/** 언급 흐름에서 고른 날 ?day=YYYY-MM-DD — 형식이 틀리면 무시 */
export function pickedDay(raw: string | null): string | null {
  return raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) && !Number.isNaN(Date.parse(raw)) ? raw : null
}

export interface UsConsensus {
  epsNext: number | null          // 내년 EPS 컨센서스
  eps90dAgo: number | null
  growth: number | null           // 이익 성장 컨센서스(%)
  analysts: number | null
  revThis: { up: number; down: number } | null    // 30일 추정 변경 · 올해
  revNext: { up: number; down: number } | null    // 30일 추정 변경 · 내년
  targets: { low: number; mean: number; median: number | null; high: number } | null
}

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const obj = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

/** yfinance 추정치 스냅샷(us_fundamentals.estimates)을 화면용으로 — 모양이 다르거나 빠진 값은 null */
export function usConsensus(estimates: Record<string, unknown> | undefined | null): UsConsensus {
  const e = obj(estimates)
  const trend = obj(e.eps_trend_1y), earn = obj(e.earnings_1y), rev = obj(e.revisions), pt = obj(e.price_targets)
  const r = (k: string) => { const x = obj(rev[k]); const up = num(x.up30), down = num(x.down30); return up == null && down == null ? null : { up: up ?? 0, down: down ?? 0 } }
  const growth = num(earn.growth)
  const low = num(pt.low), mean = num(pt.mean), high = num(pt.high)
  return {
    epsNext: num(trend.current) ?? num(earn.avg),
    eps90dAgo: num(trend.d90),
    growth: growth == null ? null : growth * 100,
    analysts: num(earn.analysts),
    revThis: r('0y'),
    revNext: r('+1y'),
    targets: low != null && mean != null && high != null && high >= low ? { low, mean, median: num(pt.median), high } : null,
  }
}

/** 목표가 범위 막대에서 값의 위치(0~100%) — 범위 밖은 양 끝에 붙인다 */
export function rangePos(v: number, low: number, high: number): number {
  if (high <= low) return 50
  return Math.min(100, Math.max(0, ((v - low) / (high - low)) * 100))
}

/** 미국 도시에 머리 첫 줄 — 'NVDA · 반도체 · 비교 SMH'(D-306). 섹터가 없으면 옛 표기 'NVDA · 미국 상장' */
export function usEyebrow(d: { ticker: string; sector?: string | null; sector_etf?: string | null }): string {
  if (!d.sector) return `${d.ticker} · 미국 상장`
  return [d.ticker, d.sector, d.sector_etf && `비교 ${d.sector_etf}`].filter(Boolean).join(' · ')
}

/** 'YYYY-MM-DD'에 n일 더하기(달력 날짜, 시간대 무관) */
export function addDays(day: string, n: number): string {
  const t = new Date(`${day}T00:00:00Z`)
  t.setUTCDate(t.getUTCDate() + n)
  return t.toISOString().slice(0, 10)
}

export interface DayRange { start: string; end: string }
/** 미국 자료 탭 기간 프리셋 — 끝 날짜에서 거꾸로 n일 */
export const RANGE_PRESETS = [
  { key: '1w', label: '1주', days: 7 },
  { key: '2w', label: '2주', days: 14 },
  { key: '4w', label: '4주', days: 28 },
] as const

/**
 * 미국 자료 탭 기간(D-306 3) — URL ?from=&to= 가 상태. 옛 ?day=X 는 X~X로 읽는다.
 * 없으면 끝 날짜(미 동부 오늘)에서 1주(시안 기본). 순서가 뒤집히면 바로 잡는다.
 */
export function evidenceRange(sp: URLSearchParams, today: string): DayRange {
  const from = pickedDay(sp.get('from'))
  const to = pickedDay(sp.get('to'))
  if (from && to) return from <= to ? { start: from, end: to } : { start: to, end: from }
  if (from || to) return { start: (from ?? to)!, end: (to ?? from)! }
  const day = pickedDay(sp.get('day'))
  if (day) return { start: day, end: day }
  return { start: addDays(today, -7), end: today }
}

/** 기간이 프리셋(끝 = 오늘, n일 전부터)과 같으면 그 키 */
export function rangePreset(r: DayRange, today: string): string | null {
  if (r.end !== today) return null
  return RANGE_PRESETS.find((p) => addDays(today, -p.days) === r.start)?.key ?? null
}

/** 미 동부 오늘(YYYY-MM-DD) — 서버 언급 흐름의 마지막 날과 같은 기준 */
export const usToday = (now = new Date()) => now.toLocaleDateString('sv-SE', { timeZone: 'America/New_York' })

/** DART 공시명의 긴 공백(원문 그대로 저장)을 한 칸으로 */
export const reportTitle = (name: string | null | undefined) => (name ?? '').replace(/\s+/g, ' ').trim() || '-'
