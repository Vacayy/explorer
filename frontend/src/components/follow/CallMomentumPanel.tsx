import { QueryState } from "@/components/shared/QueryState"
import { Link } from "react-router-dom"
import { ChevronRight, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { CallAccel, CallMomentumCandidate } from "@/types"
import { useCallMomentum } from "@/hooks/useTranscripts"
import { formatPercent } from "@/utils/format"

export const STATUS = { new: { label: "새 동인", cls: "text-up-ink border-up/40" }, accelerating: { label: "가속", cls: "text-hypothesis border-hypothesis/40" } } as const
export const SOURCE: Record<string, string> = { release: "보도자료", commentary: "CFO 코멘터리", transcript: "컨콜" }
export const GUIDE: Record<string, string> = { raised: "상향", lowered: "하향", initiated: "신규", maintained: "유지" }

/** 컨콜 브라우저 맨 위 한 줄 — 이번 시즌 후보 수·상위 3. 조회 상태와 실패를 함께 표시 */
export function MomentumStrip() {
  const q = useCallMomentum()
  return <QueryState query={q} loading={<Skeleton className="h-11 w-full rounded-card" />} isEmpty={() => false}>{data => {
    const { season, candidates } = data
    const top = [...candidates].sort((a, b) => b.score - a.score).slice(0, 3)
    return <Card className="py-0 shadow-none">
      <CardContent className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 text-sm">
        <TrendingUp aria-hidden="true" className="size-4 text-primary" />
        <span className="font-medium">실적 발언 모멘텀</span>
        <span className="text-caption text-muted-foreground">{season.label} · 발표 분석 {season.reported}개사 · 새 모멘텀 {candidates.length}건</span>
        {top.map(c => <Badge key={`${c.ticker}-${c.event_date}`} variant="outline" className="font-normal" asChild>
          <Link to={`/follow/transcripts?view=season&pick=${c.ticker}#momentum`}>{c.ticker} <span className="tabular-nums text-muted-foreground">{c.score.toFixed(0)}</span></Link>
        </Badge>)}
        <Button variant="ghost" size="xs" className="ml-auto" asChild>
          <Link to="/follow/transcripts?view=season#momentum">자세히 <ChevronRight /></Link>
        </Button>
      </CardContent>
    </Card>
  }}</QueryState>
}

/** 후보 카드 — 지난 시즌 기록(시즌 개요 새 모멘텀 후보 아래)에서 쓴다 */
export function CandidateCard({ c }: { c: CallMomentumCandidate }) {
  const growth = c.drivers.filter(d => d.status === "new" || d.status === "accelerating")
  const guide = c.guidance.filter(g => g.direction !== "maintained" && g.direction !== "unknown")
  return <Card>
    <CardHeader className="pb-2">
      <CardTitle className="flex flex-wrap items-baseline gap-2 text-base">
        {c.name ?? c.ticker} <span className="text-sm font-normal text-muted-foreground">{c.ticker} · {c.event_date} 실적 발표</span>
        <Badge variant="secondary" className="ml-auto tabular-nums">점수 {c.score.toFixed(0)}</Badge>
      </CardTitle>
      <CardDescription>
        근거: {c.sources.map(s => SOURCE[s] ?? s).join(" · ")}
        {c.tone != null && c.prev_tone != null && ` · 수요 어조 ${c.prev_tone}→${c.tone}`}
      </CardDescription>
    </CardHeader>
    <CardContent className="space-y-3">
      {c.accel?.on && <p className="text-sm"><span className="font-medium text-up-ink">기대 초과 가속</span> · {accelText(c.accel)}</p>}
      {c.summary && <div className="rounded-lg bg-muted/50 px-3 py-2.5">
        <p className="text-caption text-hypothesis">AI 요약 · 아래 근거로 작성</p>
        <p className="mt-1 text-sm leading-relaxed">{c.summary}</p>
      </div>}
      <ul className="space-y-2">{growth.map(d => <li key={d.name} className="space-y-1">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
          <Badge variant="outline" className={`text-caption ${STATUS[d.status as keyof typeof STATUS].cls}`}>{STATUS[d.status as keyof typeof STATUS].label}</Badge>
          {d.name}{d.magnitude && <span className="text-caption font-normal text-muted-foreground">{d.magnitude}</span>}
        </p>
        <blockquote className="border-l-2 pl-3 text-caption text-muted-foreground">“{d.quote}” — {SOURCE[d.source] ?? d.source}</blockquote>
      </li>)}</ul>
      {guide.length > 0 && <ul className="space-y-1 border-t pt-2">{guide.map(g => <li key={g.metric + g.quote} className="text-sm">
        <span className={g.direction === "raised" ? "text-up-ink" : g.direction === "lowered" ? "text-down-ink" : ""}>가이던스 {GUIDE[g.direction]}</span> · {g.metric}
        <p className="text-caption text-muted-foreground">“{g.quote}”</p>
      </li>)}</ul>}
      {c.qa_focus.length > 0 && <p className="text-caption text-muted-foreground">애널리스트 질문 초점: {c.qa_focus.join(" · ")}</p>}
    </CardContent>
  </Card>
}

function accelText(a: CallAccel): string {
  if (a.basis === "numeric") {
    const extra = [a.beat != null ? `컨센서스 대비 ${formatPercent(a.beat)}` : "", a.guidance_raised ? "성장 가이던스 상향" : ""].filter(Boolean)
    return `매출 성장률 ${formatPercent(a.g_prev)} → ${formatPercent(a.g_now)} (${a.quarter})${extra.length ? " · " + extra.join(" · ") : ""}`
  }
  if (a.basis === "quote") return a.quote ? `“${a.quote}”` : "원문 근거"
  return ""
}
