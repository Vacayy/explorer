import { QueryState } from "@/components/shared/QueryState"
import { Link } from "react-router-dom"
import { AlertTriangle, ChevronDown, ChevronRight, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { CallAccel, CallMomentumCandidate } from "@/types"
import { useCallMomentum } from "@/hooks/useTranscripts"
import { formatPercent } from "@/utils/format"

const STATUS = { new: { label: "새 동인", cls: "text-up border-up/40" }, accelerating: { label: "가속", cls: "text-hypothesis border-hypothesis/40" } } as const
const SOURCE: Record<string, string> = { release: "보도자료", commentary: "CFO 코멘터리", transcript: "컨콜" }
const GUIDE: Record<string, string> = { raised: "상향", lowered: "하향", initiated: "신규", maintained: "유지" }

/** 실적 발언 새 모멘텀(D-217, 2026-11-04 재정의) — 기대를 넘어 가팔라진 성장(가속)·성장 가이던스 상향·수요 어조 상승 중심.
 * 인용문은 원문 대조를 통과한 것만. 전면은 이번 시즌 새 모멘텀, 이어지는 모멘텀은 접어서, 지난 시즌은 기록으로. */
export function CallMomentumPanel() {
  const q = useCallMomentum()
  return <QueryState query={q} loading={<Skeleton className="h-64 w-full rounded-card" />} isEmpty={() => false}>{data => {
    const { season, candidates, history, coverage: cov, sec_configured } = data
    const continuing = data.continuing ?? []
    return <div className="space-y-4">
      {!sec_configured && <div role="alert" className="flex gap-2 rounded-lg border border-chart-warning/40 bg-chart-warning/10 p-3 text-sm">
        <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-chart-warning" />
        <span>SEC 실적 보도자료 수집이 멈춰 있습니다. SEC는 연락처가 있는 요청만 받습니다 — <code>.env</code>에 <code>SEC_USER_AGENT="이름 이메일"</code>을 넣어 주세요.</span>
      </div>}
      <p className="text-caption text-muted-foreground">
        대상 {cov.universe}개사 · 보도자료 {cov.with_releases}개사 · 컨콜 {cov.with_transcripts}개사 · 분석 문서 {cov.extracted_docs}건
        {cov.failed_docs > 0 && ` (실패 ${cov.failed_docs})`} · 분기 비교 가능 {cov.comparable}개사. 매일 07:20 수집·분석(10:30·13:30에 이번 시즌 녹취록 다시 확인), 월요일 07:10 텔레그램.
      </p>
      <h3 className="text-sm font-semibold">{season.label} <span className="font-normal text-muted-foreground">· {season.start.slice(5).replace("-", "/")}부터 · 발표 분석 {season.reported}개사</span></h3>
      {!candidates.length
        ? <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
            {!cov.comparable ? "직전 분기와 비교할 자료가 아직 쌓이는 중입니다. 같은 회사의 실적 발표가 두 번 이상 분석되면 판정합니다."
              : season.reported ? `이번 시즌에 실적을 낸 ${season.reported}개사 중 아직 새 모멘텀으로 판정된 곳이 없습니다.`
              : "이번 시즌 실적 발표가 아직 분석되지 않았습니다. 발표가 나오는 대로 매일 07:20에 판정합니다."}
          </CardContent></Card>
        : candidates.map(c => <CandidateCard key={`${c.ticker}-${c.event_date}`} c={c} />)}
      {continuing.length > 0 && <Collapsible>
        <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="w-full justify-between">
          <span>이어지는 모멘텀 <span className="font-normal text-muted-foreground">· {continuing.length}건</span></span>
          <ChevronDown aria-hidden="true" className="size-4" /></Button></CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 pt-2">{continuing.map(c => <CandidateCard key={`${c.ticker}-${c.event_date}`} c={c} />)}</CollapsibleContent>
      </Collapsible>}
      {history.length > 0 && <div className="space-y-2 border-t pt-4">
        <h3 className="text-sm font-semibold text-muted-foreground">지난 시즌 기록</h3>
        {history.map(h => <Collapsible key={h.key}>
          <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="w-full justify-between">
            <span>{h.label} <span className="font-normal text-muted-foreground">· 새 모멘텀 {h.candidates.length}건</span></span>
            <ChevronDown aria-hidden="true" className="size-4" /></Button></CollapsibleTrigger>
          <CollapsibleContent className="space-y-3 pt-2">{h.candidates.map(c => <CandidateCard key={`${c.ticker}-${c.event_date}`} c={c} />)}</CollapsibleContent>
        </Collapsible>)}
      </div>}
    </div>
  }}</QueryState>
}

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
          <Link to={`/us/${c.ticker}`}>{c.ticker} <span className="tabular-nums text-muted-foreground">{c.score.toFixed(0)}</span></Link>
        </Badge>)}
        <Button variant="ghost" size="xs" className="ml-auto" asChild>
          <Link to="/follow/transcripts?view=season">자세히 <ChevronRight /></Link>
        </Button>
      </CardContent>
    </Card>
  }}</QueryState>
}

function CandidateCard({ c }: { c: CallMomentumCandidate }) {
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
      {c.accel?.on && <p className="text-sm"><span className="font-medium text-up">기대 초과 가속</span> · {accelText(c.accel)}</p>}
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
        <span className={g.direction === "raised" ? "text-up" : g.direction === "lowered" ? "text-down" : ""}>가이던스 {GUIDE[g.direction]}</span> · {g.metric}
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
