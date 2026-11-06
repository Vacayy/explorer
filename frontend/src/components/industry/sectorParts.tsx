import { InfoTip } from "@/components/shared/InfoTip"
import { polyline, rebase } from "@/lib/svgLines"
import { cn } from "@/lib/utils"
import { formatLevel, formatNumber } from "@/utils/format"
import type { SectorBenchmark } from "@/types"

/**
 * 산업 › 섹터 지도·섹터 화면 공통 조각 (ia-redesign §4.35, D-327).
 * 대표지수 표시 규칙(D-327-4): ETF면 'ETF 이름 · 코드' + ⓘ(무엇을 따라가는지), 대응 ETF가 없으면 'Explorer 계산 지수' + ⓘ(계산 방식).
 */

export const RS_INFO = "섹터 종목을 시가총액으로 가중한 수익률을 18개 섹터끼리 백분위(0~100)로 비교합니다. 장기 RS는 약 11개월, 단기 RS는 1개월 수익률입니다. 대표지수(ETF)가 아니라 섹터 종목으로 계산합니다."

export function benchmarkTip(b: SectorBenchmark): string {
  if (b.kind === "etf") return `${b.name}(${b.ticker}) — ${b.tracks} 지수를 따라가는 ETF입니다. 이 섹터의 대표지수로 씁니다.${b.note ? ` ${b.note}` : ""} 대응 ETF가 없는 섹터는 Explorer 계산 지수를 씁니다.`
  return `대응 ETF가 없어 Explorer가 이 섹터 종목을 시가총액으로 가중해 계산한 지수입니다(최신 주식 수 고정, 날마다 이어 붙임).${b.note ? ` ${b.note}` : ""}`
}

export const benchmarkName = (b: SectorBenchmark) => b.kind === "etf" ? b.name ?? "-" : "Explorer 계산 지수"

/** 'KODEX 반도체 091160 ⓘ' · 'Explorer 계산 지수 ⓘ' */
export function BenchmarkLabel({ b, className }: { b: SectorBenchmark; className?: string }) {
  return <span className={cn("inline-flex items-center gap-1 text-[13px] text-ink-2", className)}>
    <span className="whitespace-nowrap">{benchmarkName(b)}</span>
    {b.kind === "etf" && <span className="font-mono text-ink-3">{b.ticker}</span>}
    <InfoTip label="대표지수 설명">{benchmarkTip(b)}</InfoTip>
  </span>
}

/** 대표지수 값 — ETF 종가는 원 단위 정수, 계산 지수는 포인트(소수 2자리) */
export const benchmarkValue = (b: SectorBenchmark, v: number | null) => b.kind === "etf" ? formatNumber(v == null ? null : Math.round(v)) : formatLevel(v)

/** 상대강도 지도 네 구역 — 가로 단기 RS, 세로 장기 RS (50 기준) */
export type Zone = "주도" | "숨 고르기" | "반등 시도" | "소외"
export function zoneOf(rsLong: number | null, rsShort: number | null): Zone | null {
  if (rsLong == null || rsShort == null) return null
  return rsLong >= 50 ? (rsShort >= 50 ? "주도" : "숨 고르기") : (rsShort >= 50 ? "반등 시도" : "소외")
}

/** 구역 이동 — 가장 오래된 궤적(3주 전) → 지금. 같으면 지금 구역만 */
export function zoneMove(g: { rs_long: number | null; rs_short: number | null; trail: { weeks_ago: number; rs_long: number | null; rs_short: number | null }[] }): string | null {
  const now = zoneOf(g.rs_long, g.rs_short)
  const old = [...g.trail].sort((a, b) => b.weeks_ago - a.weeks_ago)[0]
  const before = old ? zoneOf(old.rs_long, old.rs_short) : null
  if (!now) return null
  return before && before !== now ? `${before} → ${now}` : now
}

/** 시안 배지(높이 20 · 6 라운드 · 11.5/500) */
export function Chip({ kind = "chip", children, className }: { kind?: "chip" | "up" | "down" | "warn" | "hyp" | "fact"; children: React.ReactNode; className?: string }) {
  const tone = { chip: "bg-chip text-ink-2", up: "bg-up-tint text-up-ink", down: "bg-down-tint text-down-ink", warn: "bg-warn-tint text-warn", hyp: "bg-hyp-tint text-hyp", fact: "bg-fact-tint text-fact" }[kind]
  return <span className={cn("inline-flex h-5 shrink-0 items-center rounded-md px-[7px] text-[11.5px] font-medium whitespace-nowrap", tone, className)}>{children}</span>
}

/** 카드 선 — 대표지수(실선) · 코스피(점선), 둘 다 시작 = 100 */
export function MiniLines({ series, kospi, accent }: { series: number[]; kospi: number[]; accent?: boolean }) {
  const a = rebase(series), k = rebase(kospi)
  const all = [...a, ...k]
  if (a.length < 2) return <div className="h-[70px]" />
  const lo = Math.min(...all), hi = Math.max(...all)
  return <svg viewBox="0 0 240 70" preserveAspectRatio="none" aria-hidden="true" className="mt-auto h-[70px] w-full shrink-0">
    {k.length > 1 && <polyline points={polyline(k, 240, 70, lo, hi)} fill="none" className="stroke-ink-3" strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />}
    <polyline points={polyline(a, 240, 70, lo, hi)} fill="none" className={accent ? "stroke-up" : "stroke-ink"} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
  </svg>
}

export const sectorPath = (name: string, query = "") => `/industry/${encodeURIComponent(name)}${query}`
