/* ── Market Today — 오늘 장중 실시간 소스 화두 (docs/specs/market-today.md) ── */
import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ChevronLeft, ChevronRight, Sparkles } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { NarrativeChipLine } from "@/components/world/NarrativeChipLine"
import { useMarketOverview } from "@/hooks/useMarketOverview"
import { useMarketToday } from "@/hooks/useMarketToday"
import { cn } from "@/lib/utils"
import { formatLevel, formatPercent } from "@/utils/format"
import type { MarketToday, TodayTopic } from "@/types"
import type { WidgetBodyProps, WidgetMeta } from "./types"

/** 한국 관례: 상승 빨강·하락 파랑 */
const tone = (v: number | null | undefined) => v == null || v === 0 ? "" : v > 0 ? "text-up-ink" : "text-down-ink"
export const kstToday = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" })
const md = (d: string) => d.slice(5).replace("-", "/").replace(/^0/, "").replace("/0", "/")

/** 보는 날 — URL `?mt=YYYY-MM-DD`(없으면 오늘). 머리(meta)와 본문이 같은 날을 본다 */
function useMtDate() {
  const [sp, setSp] = useSearchParams()
  const date = sp.get("mt")
  const go = (d: string | null) => setSp(prev => {
    const n = new URLSearchParams(prev)
    if (!d || d === kstToday()) n.delete("mt"); else n.set("mt", d)
    return n
  }, { replace: true })
  return [date, go] as const
}

const WD = ["일", "월", "화", "수", "목", "금", "토"]
const dayLabel = (d: string) => `${md(d)}(${WD[new Date(`${d}T12:00:00+09:00`).getUTCDay()]})`

export function useMarketTodayMeta(): WidgetMeta {
  const [date] = useMtDate()
  const q = useMarketToday(null, date)
  const d = q.data
  const c = d?.current
  if (!d?.trade_date) return { asOf: null }
  const day = d.trade_date === kstToday() ? "오늘" : md(d.trade_date)
  // 첫 정리 전에도 머리 두 줄을 유지 — 정리가 나오면서 머리 높이가 바뀌지 않게
  if (!c) return { asOf: d.next_slot ? `다음 정리 ${d.next_slot}` : null, sub: `${day} 장중 · 첫 정리 전` }
  return { asOf: `${c.label} 정리`, sub: `${day} 장중 · 텔레그램 ${c.telegram} · 뉴스 ${c.news}` }
}

export function MarketTodayBody({ w, h }: WidgetBodyProps) {
  const [date, go] = useMtDate()
  const [slot, setSlot] = useState<string | null>(null)
  useEffect(() => setSlot(null), [date])
  const q = useMarketToday(slot, date)
  const latest = useMarketToday(null, date)
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const c = d.current
  const isToday = d.trade_date === kstToday()
  const n = h <= 3 ? 2 : w <= 4 ? 3 : 5
  // 첫 정리 전에도 날짜 줄·타임라인·요약 줄은 그대로 두고 아래 목록 자리만 비운다(레이아웃 이동 없음)
  return <div className="flex h-full min-h-0 flex-col gap-3">
    <DayNav day={d} onGo={go} />
    {/* 하루 경로는 가장 늦은 회차의 것 — 고른 회차는 점으로만 표시 */}
    <IntradayTimeline day={latest.data ?? d} picked={c?.slot ?? null} onPick={setSlot} />
    <p className="flex items-center gap-1.5 text-[11.5px] text-hyp"><Sparkles className="size-3" aria-hidden="true" />AI 요약 · 실시간 소스에서 주로 나온 얘기{d.next_slot ? ` · 다음 정리 ${d.next_slot}` : ""}</p>
    {!c
      ? <p className="text-sm text-muted-foreground">{isToday && d.next_slot ? `오늘 첫 정리는 ${d.next_slot}에 나와요.` : isToday ? "오늘은 장중 정리가 없어요." : "이날은 장중 정리가 없어요."}</p>
      : c.topics.length === 0
      ? <p className="text-sm text-muted-foreground">이 회차에는 출처로 확인된 화두가 없어요.</p>
      : <ul className="-mr-2 min-h-0 divide-y overflow-y-auto pr-2">{c.topics.slice(0, n).map(t => <TopicRow key={t.title} t={t} compact={h <= 3} links={c.links_ready} />)}</ul>}
  </div>
}

/** 날짜 넘기기 — ‹ 앞 날 · 보는 날 · 뒷 날 › (회차가 있는 날로만 이동, 오늘은 회차 전이어도 갈 수 있다) */
function DayNav({ day, onGo }: { day: MarketToday; onGo: (d: string | null) => void }) {
  if (!day.trade_date) return null
  const today = day.trade_date === kstToday()
  return <div className="flex items-center gap-1 text-[12.5px] text-ink-2">
    <Button variant="ghost" size="icon-xs" aria-label={day.prev_date ? `${dayLabel(day.prev_date)} 보기` : "이전 날 없음"} disabled={!day.prev_date}
      onClick={() => day.prev_date && onGo(day.prev_date)}><ChevronLeft aria-hidden /></Button>
    <span className="min-w-[72px] text-center font-mono tabular-nums">{today ? `오늘 ${dayLabel(day.trade_date)}` : dayLabel(day.trade_date)}</span>
    <Button variant="ghost" size="icon-xs" aria-label={day.next_date ? `${dayLabel(day.next_date)} 보기` : "다음 날 없음"} disabled={!day.next_date}
      onClick={() => day.next_date && onGo(day.next_date)}><ChevronRight aria-hidden /></Button>
    {!today && <Button variant="ghost" size="xs" className="ml-auto" onClick={() => onGo(null)}>오늘로</Button>}
  </div>
}

/* ── 장중 타임라인(시안 Home) — 코스피 5분 경로 · 지금(또는 마감) 선 · 회차 점(누르면 그 회차) ── */
const OPEN = 9 * 60, CLOSE = 15 * 60 + 30
const X0 = 1, X1 = 96.5, XMAX = 99   // % — 장 마감(15:30)은 96.5%, 마감 뒤 회차는 끝에 붙인다
const mins = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
const xAt = (m: number) => Math.min(XMAX, X0 + Math.max(0, m - OPEN) / (CLOSE - OPEN) * (X1 - X0))
const kstMinutes = () => { const t = new Date().toLocaleTimeString("en-GB", { timeZone: "Asia/Seoul", hour12: false }); return mins(t) }
/** 오늘 정리 시각(D-309) — 아직 안 나온 회차는 빈 점으로 자리만 보인다 */
export const SCHEDULE = ["09:30", "11:30", "15:00", "16:00"]

function IntradayTimeline({ day, picked, onPick }: { day: MarketToday; picked: string | null; onPick: (slot: string) => void }) {
  const live = day.trade_date === kstToday()
  // 오늘은 홈 › 한국 시장과 같은 장중 경로(index_intraday)·현재값을 쓴다 — 회차 저장값은 그 회차 시점이라 지금 값과 다르다.
  // 지난 날은 회차에 저장된 경로를 쓴다.
  const ov = useMarketOverview("kr")
  const k1 = live ? ov.data?.indices.find(i => i.key === "kospi") : undefined
  const livePath = k1?.session.trade_date === day.trade_date ? (k1.ranges.find(r => r.key === "1d")?.points ?? []) : []
  const market = day.current?.market
  const path: [string, number][] = livePath.length > 1 ? livePath.map(p => [p.t, p.v] as [string, number]) : market?.path ?? []
  const [now, setNow] = useState(kstMinutes)
  useEffect(() => {
    if (!live) return
    const id = window.setInterval(() => setNow(kstMinutes()), 60_000)
    return () => window.clearInterval(id)
  }, [live])
  const closed = !live || now >= CLOSE
  const nowX = closed ? X1 : xAt(now)
  const vals = path.map(p => p[1])
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const pts = path.map(([t, v]) => `${xAt(mins(t))},${hi === lo ? 25 : 38 - (v - lo) / (hi - lo) * 30}`).join(" ")
  const k = livePath.length > 1 && k1?.value != null ? { value: k1.value, change_pct: k1.change_pct, at: k1.session.last_time }
    : market?.kospi ? { value: market.kospi.value, change_pct: market.kospi.change_pct, at: market.kospi.at } : null
  const done = new Set(day.slots.map(s => s.label.replace(" 마감", "")))
  const pending = live ? SCHEDULE.filter(t => !done.has(t)) : []
  return <div className="glass flex flex-col gap-1 rounded-2xl px-3 pt-2.5 pb-1.5" data-mt-intraday>
    <div className="flex justify-between text-[11.5px] text-ink-2">
      <span>코스피 장중</span>
      {k && <span>코스피 <span className="font-mono tabular-nums">{formatLevel(k.value)}</span> <span className={cn("font-mono tabular-nums", tone(k.change_pct))}>{formatPercent(k.change_pct)}</span>{k.at && <span className="ml-1.5 font-mono text-[10.5px] text-ink-3">{k.at}</span>}</span>}
    </div>
    <div className="relative h-16">
      <svg viewBox="0 0 100 48" preserveAspectRatio="none" className="absolute inset-x-0 top-0 h-12 w-full" role="img" aria-label="장중 타임라인: 코스피 경로와 정리 회차">
        <rect x={X0} y="4" width={X1 - X0} height="38" rx="1.2" className="fill-chip" />
        {path.length > 1 && <polyline points={pts} fill="none" vectorEffect="non-scaling-stroke" strokeWidth="1.6"
          className={(k?.change_pct ?? 0) < 0 ? "stroke-down" : "stroke-up"} />}
        <line x1={nowX} x2={nowX} y1="1" y2="44" vectorEffect="non-scaling-stroke" strokeWidth="1.2" className="stroke-ink" />
      </svg>
      <span className="absolute top-0.5 -translate-x-full pr-1 font-mono text-[10px] whitespace-nowrap text-ink" style={{ left: `${nowX}%` }}>{closed ? "마감" : `${String(Math.floor(now / 60)).padStart(2, "0")}:${String(now % 60).padStart(2, "0")}`}</span>
      {/* 09:30 회차 점이 있으면 그 라벨과 겹치므로 시작 시각은 생략 */}
      {!day.slots.some(s => s.label === "09:30") && !pending.includes("09:30") &&
        <span className="absolute bottom-0 font-mono text-[10px] text-ink-3 max-sm:hidden" style={{ left: `${X0}%` }}>09:00</span>}
      {day.slots.map(s => {
        const on = s.slot === picked
        return <Button key={s.slot} variant="ghost" aria-pressed={on} aria-label={`${s.label} 회차 보기`} onClick={() => onPick(s.slot)}
          className="absolute top-[34px] h-auto -translate-x-1/2 flex-col gap-[3px] rounded-md px-1 py-0.5 hover:bg-transparent"
          style={{ left: `${xAt(mins(s.label))}%` }}>
          <span aria-hidden className={cn("rounded-full border-[1.6px] border-ink", on ? "size-3 bg-ink" : "size-[9px] bg-surface")} />
          <span className={cn("font-mono text-[10.5px] leading-none", on ? "font-semibold text-ink" : "font-normal text-ink-3")}>{s.label.replace(" 마감", "")}</span>
        </Button>
      })}
      {pending.map(t => <span key={t} aria-label={`${t} 정리 예정`}
        className="absolute top-[34px] flex -translate-x-1/2 flex-col items-center gap-[3px] px-1 py-0.5" style={{ left: `${xAt(mins(t))}%` }}>
        <span aria-hidden className="size-[9px] rounded-full border-[1.6px] border-ink-3/60 bg-transparent" />
        <span className="font-mono text-[10.5px] leading-none text-ink-3/70">{t}</span>
      </span>)}
    </div>
  </div>
}

/** links = 이 회차 내러티브 연결을 계산했는가 — 아니면(Partial) 칩 줄을 그리지 않는다(§9.4) */
export function TopicRow({ t, compact, links, full = false }: { t: TodayTopic; compact: boolean; links: boolean
  /** 본문을 줄이지 않는다(홈 › 한국 시장 ② — 칸 안 스크롤로 푼다) */
  full?: boolean }) {
  return <li className="flex flex-col gap-[5px] py-[11px] first:pt-0">
    <div className="flex items-center gap-2">
      <span className="text-[14.5px] font-semibold leading-snug">{t.title}</span>
      {t.continuing && <Badge variant="outline">이어짐</Badge>}
      <EchoDots n={t.echo} title={t.sources.map(s => s.publisher).join(" · ")} />
    </div>
    <p className={cn("text-[13px] leading-[1.6] text-ink-2", !full && "line-clamp-2")}>{t.body}</p>
    {!compact && <div className="flex flex-wrap gap-x-2.5 gap-y-0.5 text-[11.5px] text-ink-3">
      {t.sources.map(s => s.doc_id
        ? <Link key={s.ref} to={`/doc/${s.doc_id}`} className="underline underline-offset-2 hover:text-ink">{s.publisher}</Link>
        : s.url ? <a key={s.ref} href={s.url} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-ink">{s.publisher}</a>
        : <span key={s.ref}>{s.publisher}</span>)}
    </div>}
    {!compact && links && <NarrativeChipLine items={t.narratives ?? []} />}
  </li>
}

/** 언급 출처 수 — 채운 점(최대 5) + 'n곳' (시안 Home) */
function EchoDots({ n, title }: { n: number; title?: string }) {
  return <span className="ml-auto inline-flex shrink-0 items-center gap-1.5 text-[11.5px] text-ink-3" title={title}>
    <span aria-hidden className="inline-flex gap-0.5">
      {Array.from({ length: 5 }, (_, i) => <span key={i} className={cn("size-1.5 rounded-full", i < n ? "bg-ink" : "bg-chip")} />)}
    </span>
    {n}곳
  </span>
}
