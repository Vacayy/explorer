/**
 * 홈 › 내 종목(ia-redesign §4.4) 순수 규칙 — 목록 정렬·특징주 순서·신호 근거 한 줄·미국 실적 배지·추적 안내 문구.
 * 화면(components/home/HomeStocksPage)과 테스트가 같이 쓴다.
 */
import type { SeasonOverview, StockGroupMember } from "@/types"
import { daysBetween } from "@/lib/seasonPhase"
import { formatPercent, formatPp, formatStockPrice } from "@/utils/format"

type Signal = StockGroupMember["signals"][number]

/** 목록 정렬 = 추적 중 → 신호 켜진 종목 → 등락 폭(절댓값) 큰 순. 등락이 없으면 뒤로. */
export function sortRows(members: StockGroupMember[]): StockGroupMember[] {
  const rank = (m: StockGroupMember) => (m.tracked ? 0 : m.signals.length ? 1 : 2)
  const move = (m: StockGroupMember) => (m.change_pct == null ? -1 : Math.abs(m.change_pct))
  return [...members].sort((a, b) => rank(a) - rank(b) || move(b) - move(a))
}

/** 추적 행은 모두, 비추적 행은 처음 limit개만(나머지는 '더 보기') */
export function splitRows(members: StockGroupMember[], limit = 6): { tracked: StockGroupMember[]; untracked: StockGroupMember[]; hidden: number } {
  const sorted = sortRows(members)
  const tracked = sorted.filter(m => m.tracked)
  const rest = sorted.filter(m => !m.tracked)
  return { tracked, untracked: rest.slice(0, limit), hidden: Math.max(0, rest.length - limit) }
}

const isHigh = (s: Signal) => s.strategy_id.startsWith("high_")
const isVolume = (s: Signal) => s.strategy_id.startsWith("volume_")

/** 특징주 대표 신호 — 신고가 먼저, 그다음 거래량 증가율 큰 것, 그 밖은 첫 신호 */
export function leadSignal(m: StockGroupMember): Signal | null {
  const high = m.signals.find(isHigh)
  if (high) return high
  const vols = m.signals.filter(isVolume).sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
  return vols[0] ?? m.signals[0] ?? null
}

/** 특징주 = 오늘 신호가 들어온 관심 종목. 순서 = 신고가 신호 먼저, 그다음 거래량 증가율 큰 순, 그 밖은 등락 폭 */
export function featured(members: StockGroupMember[]): StockGroupMember[] {
  const score = (m: StockGroupMember): [number, number] => {
    const s = leadSignal(m)
    if (!s) return [3, 0]
    if (isHigh(s)) return [0, Math.abs(m.change_pct ?? 0)]
    if (isVolume(s)) return [1, s.value ?? 0]
    return [2, Math.abs(m.change_pct ?? 0)]
  }
  return members.filter(m => m.signals.length).sort((a, b) => {
    const [ra, va] = score(a), [rb, vb] = score(b)
    return ra - rb || vb - va
  })
}

/** 신호 근거 숫자 한 줄 — 거래량 증가는 전일 대비 %, 신고가는 고가와 직전 고점, 그 밖은 값·기준 */
export function signalDetail(s: Signal, market?: string | null): string | null {
  if (s.value == null) return null
  if (isVolume(s)) return `거래량 전일 대비 ${formatPercent(s.value)}`
  if (isHigh(s) && s.reference != null) return `고가 ${formatStockPrice(s.value, market)} — 직전 고점 ${formatStockPrice(s.reference, market)} 돌파`
  return s.reference != null ? `${formatStockPrice(s.value, market)} · 기준 ${formatStockPrice(s.reference, market)}` : null
}

export interface EarningsBadge { label: string; to: string | null }

/**
 * 미국 종목 실적 배지 — 시즌 화면 자료(/transcript/season)에서. 곧 발표면 '실적 D-n'(당일은 '실적 오늘'),
 * 발표가 지났으면 'MM/DD · ±x%p'(첫 거래일 업종 대비)와 콜 상세 링크. 팔로우 밖 티커는 없음.
 */
export function earningsBadge(ticker: string, season: SeasonOverview | undefined, today: string): EarningsBadge | null {
  if (!season) return null
  const next = season.upcoming.filter(u => u.ticker === ticker && u.event_date >= today).sort((a, b) => a.event_date.localeCompare(b.event_date))[0]
  if (next) {
    const d = daysBetween(today, next.event_date)
    return { label: d === 0 ? "실적 오늘" : `실적 D-${d}`, to: next.transcript_id ? `/follow/transcripts?t=${next.transcript_id}` : null }
  }
  const done = season.reported.filter(r => r.ticker === ticker).sort((a, b) => b.event_date.localeCompare(a.event_date))[0]
  if (!done) return null
  const md = `${done.event_date.slice(5, 7)}/${done.event_date.slice(8, 10)}`
  return { label: done.d1 == null ? `실적 ${md}` : `실적 ${md} · ${formatPp(done.d1, 1)}`, to: done.transcript_id ? `/follow/transcripts?t=${done.transcript_id}` : null }
}

/** 추적을 켰을 때 알림 범위 — 미국 티커는 국내 장 마감 점검 때 마지막 미국 종가로 판정한다 */
export const trackedNotice = (market?: string | null) =>
  market === "us" ? "장 마감 점검 때 미국 종가로 조건 충족·새 신호를 알립니다." : "조건 충족·급등락·공시를 알립니다."

/** 시장 표기 — 미국 티커는 '미국', 국내는 KOSPI·KOSDAQ 그대로 */
export const marketLabel = (market?: string | null) => (market === "us" ? "미국" : market ?? "")
