// 발표 캘린더 (ia-redesign §4.6a 캘린더 규칙) — 거래일마다 막대 하나, 높이 = 그날 팔로우 기업 발표 수.
// 핵심 몫은 아래쪽 진한 채움, 미확정 예정일은 점선 테두리. 막대를 누르면 아래 '그날 발표'가 바뀐다(?day=).
import { Link, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { InfoTip } from "@/components/shared/InfoTip"
import { CoreBadge, Meta, Pp, Section, expectationStatus, mmdd, patchParams } from "@/components/follow/season/seasonUi"
import { calendarBars, calendarSummary, defaultCalendarDay, weekOf } from "@/lib/seasonBoard"
import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/format"
import type { SeasonOverview } from "@/types"

/** 막대 위 숫자를 보이는 기준 — 이 수 이상인 날과 선택한 날만 */
const LABEL_MIN = 8

export function SeasonCalendar({ d, today }: { d: SeasonOverview; today: string }) {
  const [params, setParams] = useSearchParams()
  const bars = calendarBars(d.calendar)
  if (!bars.length) {
    return <Section title="발표 캘린더"><Meta>이번 시즌 발표 일정이 아직 없습니다.</Meta></Section>
  }
  const sum = calendarSummary(d.calendar, today)
  const requested = params.get("day")
  const picked = requested && d.calendar.some((x) => x.date === requested) ? requested : defaultCalendarDay(d.calendar, today)
  const max = Math.max(1, ...bars.map((b) => b.total))
  const week = weekOf(today)
  const pick = (date: string) => setParams((p) => patchParams(p, { day: date }), { replace: true, preventScrollReset: true })
  const day = d.calendar.find((x) => x.date === picked)
  const coreSet = new Set(d.core.tickers.map((t) => t.ticker))
  const reported = new Map(d.reported.map((r) => [r.ticker, r]))
  const upcoming = new Map(d.upcoming.map((u) => [u.ticker, u]))

  return (
    <Section>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="flex items-center gap-1 text-[15px] font-semibold">
          발표 캘린더
          <InfoTip label="발표 캘린더 설명">
            팔로우 기업의 이번 시즌 발표 수를 거래일마다 막대로 보입니다. 진한 부분은 핵심 종목, 점선은 회사가 아직 확정하지 않은 예정일입니다. 막대를 누르면 그날 발표한 종목이 아래에 나옵니다.
          </InfoTip>
        </h2>
        <span className="text-caption text-muted-foreground">
          이번 주 남은 발표 <b className="tabular-nums text-foreground">{sum.weekLeft}</b>곳 · 핵심 <b className="tabular-nums text-foreground">{sum.weekLeftCore}</b>
          {sum.peak && <> · 가장 많은 날 {mmdd(sum.peak.date)} <span className="tabular-nums">{sum.peak.total}</span>곳</>}
        </span>
      </div>

      <div className="overflow-x-auto">
        <div className="flex h-36 min-w-max items-stretch gap-px pt-5 sm:min-w-0" role="group" aria-label="날짜별 발표 수">
          {bars.map((b, i) => {
            const isToday = b.date === today
            const inWeek = b.date >= week.start && b.date <= week.end
            const sel = b.date === picked
            const isLast = i === bars.length - 1
            const prev = bars[i - 1]
            const tick = !prev || prev.date.slice(5, 7) !== b.date.slice(5, 7) || (prev.date.slice(8) < "15" && b.date.slice(8) >= "15")
            const h = (b.total / max) * 100
            const coreH = b.total ? (b.core / b.total) * 100 : 0
            const estimated = b.total > 0 && b.estimated > 0
            return (
              <Button key={b.date} variant="ghost" disabled={!b.total} onClick={() => pick(b.date)} aria-pressed={sel}
                aria-label={`${mmdd(b.date)} 발표 ${b.total}곳${b.core ? ` · 핵심 ${b.core}` : ""}${estimated ? ` · 예정 ${b.estimated}` : ""}`}
                className={cn("relative h-full min-w-[5px] flex-1 flex-col items-stretch justify-end gap-0 rounded-none p-0 pb-4 hover:bg-muted disabled:opacity-100",
                  inWeek && "bg-muted/60", isToday && "border-l border-foreground", isLast && "border-r border-dashed border-muted-foreground")}>
                {isToday && <span className="absolute -top-5 left-0.5 text-[10px] font-medium text-foreground">오늘</span>}
                {isLast && <span className="absolute -top-5 right-0.5 whitespace-nowrap text-[10px] text-muted-foreground max-sm:hidden">시즌 마지막 발표 {mmdd(b.date)}</span>}
                {(b.total >= LABEL_MIN || (sel && b.total > 0)) && <span className="text-center text-[10px] tabular-nums text-muted-foreground">{b.total}</span>}
                {b.total > 0 && (
                  <span style={{ height: `${h}%` }}
                    className={cn("mx-auto flex w-full max-w-[18px] flex-col justify-end", estimated ? "border border-dashed border-muted-foreground" : "bg-muted-foreground/30",
                      sel && "outline-2 outline-offset-1 outline-foreground")}>
                    <span style={{ height: `${coreH}%` }} className="block w-full bg-foreground/80" />
                  </span>
                )}
                {tick && <span className="absolute bottom-0 left-0 whitespace-nowrap text-[10px] tabular-nums text-muted-foreground">{mmdd(b.date)}</span>}
              </Button>
            )
          })}
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-caption text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 bg-foreground/80" />핵심 종목</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 bg-muted-foreground/30" />그 밖의 발표</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 border border-dashed border-muted-foreground" />예정(미확정)</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 bg-muted" />이번 주</span>
      </div>

      {day && (
        <div className="flex flex-col gap-2 border-t pt-3" data-calendar-day={day.date}>
          <h3 className="text-sm font-semibold">
            {mmdd(day.date)} {day.date === today ? "오늘 " : ""}발표 <span className="tabular-nums">{formatNumber(day.total)}</span>곳
            {day.total > day.confirmed && <span className="font-normal text-muted-foreground"> · 예정 {day.total - day.confirmed}</span>}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {day.tickers.map((t) => {
              const r = reported.get(t), u = upcoming.get(t)
              const to = r?.transcript_id ? `/follow/transcripts?t=${r.transcript_id}` : `/us/${t}`
              return (
                <Badge key={t} variant="outline" asChild className="h-7 gap-1.5 rounded-none px-2 font-normal hover:bg-muted">
                  <Link to={to} title={r?.name ?? u?.name ?? t}>
                    <span className="font-mono font-semibold">{t}</span>
                    {coreSet.has(t) && <CoreBadge core={["pinned"]} />}
                    {r ? <Pp v={r.d1} className="text-caption" />
                      : u ? <span className="text-caption text-muted-foreground">{expectationStatus(u.expectation)}</span> : null}
                  </Link>
                </Badge>
              )
            })}
          </div>
        </div>
      )}
    </Section>
  )
}
