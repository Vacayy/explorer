import { useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ErrorState } from '@/components/shared/ErrorState'
import { InfoTip } from '@/components/shared/InfoTip'
import { useCompanyEvidence } from '@/hooks/useCompanyEvidence'
import { addDays, evidenceRange, pickedDay, RANGE_PRESETS, rangePreset, shortDate, usToday, type DayRange } from '@/lib/dossier'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/utils/format'
import { CompanyEvidence, sourceLabels } from '@/components/company/CompanyEvidence'

type Setter = (patch: Record<string, string | null>) => void

/**
 * 도시에 '자료' 탭(국내 /analyze/:code/mentions · 미국 /us/:t?tab=evidence, ia-redesign §4.13):
 * 30일 언급 흐름 막대 · 출처별 건수(누르면 ?source=) → 자료 목록.
 * 국내 = 막대를 누르면 그날(?day=). 미국 = 기간(?from=&to=, 기본 최근 1주, 막대를 끌거나 1·2·4주) + 기간 AI 요약(누를 때만, D-306 3).
 * 미국의 옛 ?day=X 는 X~X 기간으로 읽는다. 국내 1일 요약은 11-04 결정으로 넣지 않는다.
 */
export function CompanyMentions({ company, market }: { company: string; market: 'kr' | 'us' }) {
  const [sp, setSp] = useSearchParams()
  const source = sp.get('source') || ''
  const set: Setter = (patch) => setSp((prev) => {
    const n = new URLSearchParams(prev)
    for (const [k, v] of Object.entries(patch)) if (v) n.set(k, v); else n.delete(k)
    n.delete('page')
    return n
  }, { replace: true, preventScrollReset: true })
  const onSource = (s: string) => set({ source: s === source ? null : s })

  if (market === 'us') {
    const today = usToday()
    const range = evidenceRange(sp, today)
    const setRange = (r: DayRange) => set({ from: r.start, to: r.end, day: null })
    return (
      <div className="space-y-3">
        <FlowCard company={company} market={market} source={source} onSource={onSource}
          isOn={(d) => d >= range.start && d <= range.end} onRange={setRange}
          head={<RangeControl range={range} today={today} onRange={setRange} />} />
        <CompanyEvidence key={`${company}:${range.start}:${range.end}`} company={company} market={market}
          range={range} summary title="기업 관련 자료" />
      </div>
    )
  }

  const day = pickedDay(sp.get('day'))
  return (
    <div className="space-y-3">
      <FlowCard company={company} market={market} source={source} onSource={onSource}
        isOn={(d) => d === day} onDay={(d) => set({ day: d === day ? null : d })}
        head={day && <Button variant="ghost" size="sm" className="h-7" onClick={() => set({ day: null })}>{shortDate(day)} 선택 지우기</Button>} />
      <CompanyEvidence key={`${company}:${day ?? ''}`} company={company} market={market}
        range={day ? { start: day, end: day } : {}} summary={false} />
    </div>
  )
}

/** 미국 기간 표시 + 1·2·4주 — 끝은 미 동부 오늘 */
function RangeControl({ range, today, onRange }: { range: DayRange; today: string; onRange: (r: DayRange) => void }) {
  const preset = rangePreset(range, today)
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2" data-evidence-range={`${range.start}~${range.end}`}>
      <span className="text-caption text-muted-foreground">기간</span>
      <span className="font-mono text-sm tabular-nums">{range.start === range.end ? range.start : `${range.start} ~ ${range.end}`}</span>
      <InfoTip label="기간 설명">미국 동부 날짜 기준입니다. 막대를 끌어 기간을 고르거나 1·2·4주를 누릅니다.</InfoTip>
      <ToggleGroup type="single" variant="outline" size="sm" value={preset ?? ''} aria-label="기간 단위"
        onValueChange={(v) => { const p = RANGE_PRESETS.find((x) => x.key === v); if (p) onRange({ start: addDays(today, -p.days), end: today }) }}>
        {RANGE_PRESETS.map((p) => <ToggleGroupItem key={p.key} value={p.key} className="h-7 px-2.5 text-xs">{p.label}</ToggleGroupItem>)}
      </ToggleGroup>
    </div>
  )
}

function FlowCard({ company, market, source, onSource, isOn, onDay, onRange, head }: {
  company: string; market: 'kr' | 'us'; source: string; onSource: (s: string) => void
  isOn: (date: string) => boolean
  /** 국내 — 막대 하나 */
  onDay?: (d: string) => void
  /** 미국 — 막대를 끌어 기간, 누르면 그날 하루 */
  onRange?: (r: DayRange) => void
  head?: ReactNode
}) {
  const q = useCompanyEvidence({ company, market, size: 1 })
  const flow = q.data?.flow
  const max = Math.max(1, ...(flow?.days.map((d) => d.count) ?? [0]))
  const peak = flow?.days.reduce((a, b) => (b.count > a.count ? b : a), flow.days[0])
  const total = flow?.days.reduce((a, b) => a + b.count, 0) ?? 0
  const anyOn = !!flow?.days.some((d) => isOn(d.date))
  // 끌기: 누른 막대(a) ~ 지금 막대(b). 손을 떼면 기간으로 확정한다
  const [drag, setDrag] = useState<{ a: string; b: string } | null>(null)
  const dragged = useRef(false)
  const dayAt = (e: PointerEvent) => (document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-day]') as HTMLElement | null)?.dataset.day
  const brush = onRange ? {
    onPointerDown: (e: PointerEvent<HTMLDivElement>) => {
      const d = dayAt(e); if (!d) return
      dragged.current = false
      setDrag({ a: d, b: d })
    },
    onPointerMove: (e: PointerEvent<HTMLDivElement>) => {
      if (!drag) return
      const d = dayAt(e)
      if (d && d !== drag.b) {
        // 실제로 끌기 시작했을 때만 포인터를 잡는다 — 그냥 누르기는 막대 버튼의 click으로 간다
        if (!dragged.current) e.currentTarget.setPointerCapture?.(e.pointerId)
        dragged.current = true
        setDrag({ ...drag, b: d })
      }
    },
    onPointerUp: () => {
      if (drag && dragged.current) onRange(drag.a < drag.b ? { start: drag.a, end: drag.b } : { start: drag.b, end: drag.a })
      setDrag(null)
      setTimeout(() => { dragged.current = false })
    },
    onPointerCancel: () => setDrag(null),
  } : {}
  const lit = (date: string) => drag ? date >= (drag.a < drag.b ? drag.a : drag.b) && date <= (drag.a < drag.b ? drag.b : drag.a) : isOn(date)
  const click = (date: string) => {
    if (dragged.current) return
    if (onRange) onRange({ start: date, end: date }); else onDay?.(date)
  }
  return (
    <Card className="gap-0 py-0" aria-label="언급 흐름" data-mention-flow>
      <header className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-3">
        <h2 className="text-section font-semibold">언급 흐름</h2>
        <span className="text-caption text-muted-foreground">최근 30일{flow ? ` · ${formatNumber(total)}건` : ''}</span>
        <InfoTip label="언급 흐름 설명">이 기업에 연결된 저장 자료를 {market === 'kr' ? '한국' : '미 동부'} 날짜로 셉니다. {onRange ? '막대를 끌면 그 기간, 누르면 그날' : '막대를 누르면 그날'} 자료만, 출처를 누르면 그 출처만 봅니다.</InfoTip>
        <span className="ml-auto" />
        {head}
      </header>
      <div className="space-y-3 px-4 py-3">
        {q.isPending ? <Skeleton className="h-28 w-full" />
          : q.isError || !flow ? <ErrorState message="언급 흐름을 불러오지 못했습니다." onRetry={() => q.refetch()} />
          : total === 0 ? <p className="py-6 text-sm text-muted-foreground">최근 30일에 이 기업과 연결된 자료가 없습니다.</p>
          : <>
            <div className={cn('flex h-28 select-none items-end gap-[2px] sm:gap-1', onRange && 'touch-pan-y')} role="group" aria-label="날짜별 자료 수" {...brush}>
              {flow.days.map((d) => {
                const on = lit(d.date)
                return (
                  <button key={d.date} type="button" data-day={d.date} onClick={() => click(d.date)} aria-pressed={on}
                    aria-label={`${shortDate(d.date)} ${d.count}건`} title={`${shortDate(d.date)} · ${d.count}건`}
                    className="group flex h-full min-w-0 flex-1 items-end focus-visible:outline-2 focus-visible:outline-ring">
                    <span className={cn('block w-full', d.count === 0 ? (on ? 'h-0.5 bg-foreground' : 'h-px bg-border') : on || (!anyOn && !drag && d === peak) ? 'bg-foreground' : 'bg-muted-foreground/35 group-hover:bg-muted-foreground/60')}
                      style={d.count ? { height: `${Math.max(4, (d.count / max) * 100)}%` } : undefined} />
                  </button>
                )
              })}
            </div>
            <div className="flex justify-between font-mono text-caption tabular-nums text-muted-foreground">
              {[0, 7, 14, 21, 29].map((i) => <span key={i}>{shortDate(flow.days[i].date)}</span>)}
            </div>
            <div className="flex flex-wrap gap-1.5" aria-label="출처별 건수">
              {flow.sources.map((s) => (
                <Button key={s.source} size="xs" variant={source === s.source ? 'default' : 'outline'} aria-pressed={source === s.source}
                  className="rounded-full" onClick={() => onSource(s.source)}>
                  {sourceLabels[s.source] ?? s.source} <span className="font-mono tabular-nums">{formatNumber(s.count)}</span>
                </Button>
              ))}
            </div>
          </>}
      </div>
    </Card>
  )
}
