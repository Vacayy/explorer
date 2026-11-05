// 실적 시즌 개요 (?view=season) — 시즌 → 섹터 → 콜 3단의 첫 단 (ia-redesign §4.6a, docs/specs/earnings-season.md §시즌 보고서)
// 위계: 머리(시즌 선택) → 진행 줄 → 발표 캘린더 → 이번 시즌 시장이 따진 것 → 반응 보드 | 새 모멘텀 후보 → 선택한 후보 → 핵심 종목 진행판
import { useEffect, type ReactNode } from "react"
import { Link, useLocation, useSearchParams } from "react-router-dom"
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { QueryState } from "@/components/shared/QueryState"
import { InfoTip } from "@/components/shared/InfoTip"
import { useHomeToday } from "@/components/home/UsSeasonBlock"
import { SeasonCalendar } from "@/components/follow/season/SeasonCalendar"
import { SeasonSectors } from "@/components/follow/season/SeasonSectors"
import { ReactionBoard } from "@/components/follow/season/ReactionBoard"
import { MomentumBoard, PickedCandidate } from "@/components/follow/season/MomentumBoard"
import { CoreBoard } from "@/components/follow/season/CoreBoard"
import { Meta, Section, mmdd } from "@/components/follow/season/seasonUi"
import { useCallMomentum, useSeason } from "@/hooks/useTranscripts"
import { momentumFor, seasonNeighbors } from "@/lib/seasonBoard"
import { seasonPhase } from "@/lib/seasonPhase"
import { formatNumber } from "@/utils/format"
import type { SeasonOverview } from "@/types"

export function SeasonView({ tabs }: { tabs: ReactNode }) {
  const [params] = useSearchParams()
  const season = params.get("season")
  const today = useHomeToday()
  const q = useSeason(season)
  const d = q.data
  // 시즌 사이(어느 시즌 발표 구간에도 없는 날)에는 고른 시즌이 없을 때만 빈 상태 — 지난 시즌은 선택기로 본다(§4.28)
  const phase = d ? seasonPhase(today, d.windows) : null
  const between = !season && phase?.state === "between" ? phase : null
  return (
    <div className="space-y-4">
      {d ? <SeasonHeader d={d} /> : <div className="space-y-2"><Skeleton className="h-8 w-72" /><Skeleton className="h-4 w-40" /></div>}
      {tabs}
      {between ? <BetweenSeasons phase={between} today={today} /> : (
        // 갱신 실패·오프라인이어도 이전 결과를 유지한다(QueryState 규약, docs/specs/frontend-api-reliability.md)
        <QueryState query={q} loading={<SeasonSkeleton />} isEmpty={() => false}>{(data) => <SeasonBody d={data} today={today} />}</QueryState>
      )}
    </div>
  )
}

function SeasonBody({ d, today }: { d: SeasonOverview; today: string }) {
  const mq = useCallMomentum()
  const momentum = momentumFor(mq.data, d.season.key)
  useHashScroll(!!mq.data)
  return (
    <div className="surface-stack flex flex-col">
      <ProgressLine d={d} />
      <SeasonCalendar d={d} today={today} />
      <SeasonSectors d={d} momentum={momentum} />
      <div className="surface-grid grid grid-cols-1 lg:grid-cols-2">
        <ReactionBoard d={d} momentum={momentum} />
        <MomentumBoard query={mq} d={d} momentum={momentum} />
      </div>
      <PickedCandidate d={d} momentum={momentum} />
      <CoreBoard d={d} today={today} momentum={momentum} />
    </div>
  )
}

/** #momentum 같은 앵커로 들어오면 데이터가 그려진 뒤 그 블록으로 내린다(홈 › 미국 시장 링크) */
function useHashScroll(ready: boolean) {
  const { hash } = useLocation()
  useEffect(() => {
    if (!ready || !hash) return
    const t = window.setTimeout(() => document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" }), 50)
    return () => window.clearTimeout(t)
  }, [ready, hash])
}

/* ---------- 머리: 시즌 이름 · 시작일 · 시즌 선택(이전·목록·다음) ---------- */
const shortSeason = (key: string) => `${key.slice(0, 4)} Q${key.slice(-1)}`

function SeasonHeader({ d }: { d: SeasonOverview }) {
  const [, setParams] = useSearchParams()
  const keys = d.windows.map((w) => w.key)
  const options = keys.includes(d.season.key) ? keys : [...keys, d.season.key].sort()
  const { prev, next } = seasonNeighbors(options, d.season.key)
  const pick = (key: string | null) => {
    if (!key) return
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set("season", key)
      for (const k of ["sector", "day", "pick", "rtab", "core"]) n.delete(k)
      return n
    })
  }
  const current = d.season.is_current
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold">{d.season.label}</h1>
        <p className="text-caption text-muted-foreground">{mmdd(d.season.start)}부터 · {current ? "진행 중" : "지난 시즌"}</p>
      </div>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon-sm" aria-label="이전 시즌" disabled={!prev} onClick={() => pick(prev)}><ChevronLeft /></Button>
        <Select value={d.season.key} onValueChange={pick}>
          <SelectTrigger className="w-44" aria-label="시즌 선택"><SelectValue /></SelectTrigger>
          <SelectContent>
            {[...options].reverse().map((k) => {
              const cur = k === d.season.key && current
              return <SelectItem key={k} value={k}>{shortSeason(k)}{cur ? " · 진행 중" : ""}</SelectItem>
            })}
          </SelectContent>
        </Select>
        <Button variant="outline" size="icon-sm" aria-label="다음 시즌" disabled={!next} onClick={() => pick(next)}><ChevronRight /></Button>
      </div>
    </div>
  )
}

/* ---------- 진행 줄: 발표 진행 · Outperform · 실적-주가 디커플링 · 반응 정리 · 오늘 바뀐 것 ---------- */
function ProgressLine({ d }: { d: SeasonOverview }) {
  const c = d.counts
  const ch = d.changes
  const groups = [
    ["반응 추가", ch.reactions], ["섹터 요약 갱신", ch.themes], ["발표 전 기대", ch.expectations], ["새 녹취록", ch.transcripts],
  ] as const
  const changed = groups.reduce((n, [, xs]) => n + xs.length, 0)
  const pct = c.followed ? (c.reported / c.followed) * 100 : 0
  return (
    <Card className="py-0">
      <Collapsible>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3 text-sm">
          <span className="flex items-center gap-2">
            <span className="text-muted-foreground">발표</span>
            <Progress value={pct} className="h-1.5 w-24" aria-label="발표 진행" />
            <span className="tabular-nums"><b>{formatNumber(c.reported)}</b> / {formatNumber(c.followed)}</span>
          </span>
          <span>Outperform&nbsp;<b className="tabular-nums text-up">{formatNumber(c.up)}</b><span className="text-muted-foreground"> / {formatNumber(c.reported)}</span></span>
          <span>실적-주가 디커플링&nbsp;&nbsp;<b className="tabular-nums">{formatNumber(c.miss_up + c.beat_down)}</b></span>
          <span>반응 정리 <b className="tabular-nums">{formatNumber(c.reactions)}</b><span className="text-muted-foreground"> · 확정 {formatNumber(c.reactions_final)}</span></span>
          <InfoTip label="진행 줄 설명">
            Outperform은 발표 후 첫 거래일에 업종 ETF보다 강했던 발표 수입니다. 실적-주가 디커플링은 EPS가 컨센서스를 밑돌았는데 주가가 강했거나({c.miss_up}), 웃돌았는데 약했던({c.beat_down}) 발표 수입니다. 매일 07:20에 갱신합니다.
          </InfoTip>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="group ml-auto" disabled={!changed}>
              오늘 바뀐 것 <span className="tabular-nums text-muted-foreground">{changed}</span>
              <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />
            </Button>
          </CollapsibleTrigger>
        </CardContent>
        <CollapsibleContent>
          <CardContent className="flex flex-col gap-1 border-t py-3 text-sm">
            {groups.filter(([, xs]) => xs.length).map(([label, xs]) => (
              <p key={label}><span className="text-muted-foreground">{label}</span> · {xs.join(" · ")}</p>
            ))}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

/* ---------- 시즌 사이 빈 상태 (§4.28) ---------- */
function BetweenSeasons({ phase, today }: { phase: Extract<ReturnType<typeof seasonPhase>, { state: "between" }>; today: string }) {
  const [, setParams] = useSearchParams()
  return (
    <Section>
      <div data-season-state="between" className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">
          {phase.next ? <>다음 실적 시즌까지 <span className="tabular-nums">D-{phase.daysToNext}</span></> : "다음 실적 시즌 일정이 아직 없습니다"}
        </h2>
        {phase.next && <Meta>{phase.next.label} · 첫 발표 {mmdd(phase.next.first)}{phase.next.first > today && phase.next.confirmed === 0 ? " (예상일)" : ""}</Meta>}
        <div className="flex flex-wrap gap-2 pt-1">
          {phase.last && <Button variant="outline" size="sm" onClick={() => setParams({ view: "season", season: phase.last!.key })}>{phase.last.label} 다시 보기</Button>}
          <Button variant="ghost" size="sm" asChild><Link to="/follow/transcripts">지난 시즌 콜 보기</Link></Button>
        </div>
      </div>
    </Section>
  )
}

function SeasonSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-busy="true" aria-label="실적 시즌 불러오는 중">
      <Skeleton className="h-12 w-full rounded-card" />
      <Skeleton className="h-48 w-full rounded-card" />
      <Skeleton className="h-80 w-full rounded-card" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2"><Skeleton className="h-96 rounded-card" /><Skeleton className="h-96 rounded-card" /></div>
    </div>
  )
}
