import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { InfoTip } from "@/components/shared/InfoTip"
import { useNarrativeTimeline } from "@/hooks/useNarrativeLinks"
import { mdDate, RULE_LABEL } from "@/lib/narrativeLinks"
import { cn } from "@/lib/utils"
import type { TimelineCellState } from "@/types"

const HOW = "Market Today 회차가 만들어지면 화두마다 이 서사와 짝을 찾습니다. 화두 태그가 서사 주제와 같고 출처가 주제 문서면 '태그 일치', 출처 2건 이상이 주제 문서면 '자료 겹침'입니다. AI가 판단하지 않고 규칙으로만 연결합니다. 회차 수에 16:00 마감 정리는 넣지 않습니다."
const STATE_LABEL: Record<TimelineCellState, string> = { linked: "연결", unlinked: "연결 없음", scheduled: "예정", absent: "회차 없음" }
const SHOW = 6

function Dot({ state }: { state: string }) {
  return <span aria-hidden="true" className={cn("inline-block size-2.5 rounded-full",
    state === "linked" ? "bg-foreground" : state === "unlinked" ? "border border-muted-foreground/60"
      : state === "scheduled" ? "border border-dashed border-muted-foreground/40" : "h-px w-2.5 rounded-none bg-muted-foreground/30")} />
}

/**
 * 내러티브 상세 오른쪽 열 맨 위 '장중 화두 타임라인' (ia-redesign §9.2) — 최근 2일 회차 격자(연결·연결 없음·예정),
 * 연결된 화두 목록(회차·제목·규칙), 집계 한 줄(수집 시작일·이번 주 회차·갱신 앞당김). 불러오지 못하면 통째로 숨긴다(§9.4).
 */
export function MarketTodayTimeline({ narrativeId }: { narrativeId: number }) {
  const q = useNarrativeTimeline(narrativeId)
  if (q.isError) return null
  const d = q.data
  // 두 날의 회차가 같으면 시각 머리는 첫 줄에만(옛 회차 날과 새 회차 날이 섞이면 줄마다)
  const sameSlots = !!d && d.days.every((x) => x.cells.map((c) => c.slot).join() === d.days[0].cells.map((c) => c.slot).join())
  return (
    <section className="space-y-2" aria-label="장중 화두 타임라인" data-mt-timeline>
      <h2 className="flex items-center gap-1 border-b pb-1 text-sm font-semibold">장중 화두 타임라인<span className="ml-auto"><InfoTip label="어떻게 연결하나요?">{HOW}</InfoTip></span></h2>
      {!d ? <Skeleton className="h-28 w-full" /> : <>
        {d.days.length > 0 && <div className="space-y-1.5 bg-muted/60 px-3 py-2" role="table" aria-label="최근 회차 연결">
          {d.days.map((day, i) => (
            <div key={day.trade_date} role="row" className="grid grid-cols-[2.5rem_repeat(4,minmax(0,1fr))] items-end gap-x-1">
              <span role="rowheader" className="pb-0.5 font-mono text-[11px] text-muted-foreground">{mdDate(day.trade_date)}</span>
              {day.cells.map((c) => (
                <span key={c.slot} role="cell" className="flex flex-col items-center gap-1" data-state={c.state}
                  aria-label={`${mdDate(day.trade_date)} ${c.label} ${STATE_LABEL[c.state as TimelineCellState] ?? c.state}`}>
                  {(!sameSlots || i === 0) && <span className="font-mono text-[10px] text-muted-foreground">{c.label.replace(" 마감", "")}</span>}
                  <Dot state={c.state} />
                </span>
              ))}
            </div>
          ))}
        </div>}
        <p className="flex flex-wrap gap-x-3 text-[11px] text-muted-foreground" aria-hidden="true">
          {(["linked", "unlinked", "scheduled"] as const).map((s) => <span key={s} className="inline-flex items-center gap-1"><Dot state={s} />{STATE_LABEL[s]}</span>)}
        </p>
        {d.items.length === 0
          ? <p className="py-1 text-sm text-muted-foreground">이번 주 Market Today에서 이 서사가 나오지 않았어요.</p>
          : <ul className="divide-y">{d.items.slice(0, SHOW).map((it) => (
            <li key={`${it.mt_id}-${it.title}`} className="grid grid-cols-[5.5rem_1fr] gap-x-2 py-2">
              <span className="font-mono text-[11px] text-muted-foreground tabular-nums">{mdDate(it.trade_date)} {it.label}</span>
              <span className="min-w-0">
                <span className="block text-sm font-medium leading-snug">{it.title}</span>
                <span className="block text-[11px] text-muted-foreground">{RULE_LABEL[it.rule]} · 출처 {it.doc_overlap}건 겹침</span>
              </span>
            </li>
          ))}</ul>}
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground" data-mt-summary>
          {d.collected_since && <span>{mdDate(d.collected_since)}부터 수집</span>}
          <span>이번 주 {d.week_sessions}회차</span>
          {d.boost && <Badge className="h-5 rounded-none px-1.5 text-[10px] font-normal">다음 갱신 앞당김</Badge>}
        </p>
      </>}
    </section>
  )
}
