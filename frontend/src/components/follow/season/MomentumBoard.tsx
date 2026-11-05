// 새 모멘텀 후보 (ia-redesign §4.6a ⑤ 오른쪽·⑥, D-217 11-04 규칙) — 새로 붙은 모멘텀(펼친 줄)과 이어지는 모멘텀(칩)으로 나누고,
// 고른 후보(?pick=)는 아래 전체 폭 카드로 가속 근거·동인 인용·가이던스·행동을 보인다. 첫 거래일 반응은 보조 정보.
import { Link, useSearchParams } from "react-router-dom"
import { AlertTriangle, ChevronDown, MessageSquare } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { QueryState } from "@/components/shared/QueryState"
import { InfoTip } from "@/components/shared/InfoTip"
import { CandidateCard, GUIDE, SOURCE, STATUS } from "@/components/follow/CallMomentumPanel"
import { CoreBadge, H3, Meta, Pp, Section, mmdd, patchParams } from "@/components/follow/season/seasonUi"
import { useDefaultWatchGroup, useToggleWatch } from "@/hooks/useGroups"
import { accelLine, raisedGuidance, toneUp, type MomentumSet } from "@/lib/seasonBoard"
import { cn } from "@/lib/utils"
import { formatPercent, formatPp } from "@/utils/format"
import type { CallMomentum, CallMomentumCandidate, SeasonItem, SeasonOverview } from "@/types"

type MomentumQuery = Parameters<typeof QueryState<CallMomentum>>[0]["query"]

/** 고른 후보 — ?pick=이 목록에 있으면 그것, 없으면 새로 붙은 첫 후보(점수순) */
function usePicked(momentum: MomentumSet) {
  const [params] = useSearchParams()
  const want = params.get("pick")
  const hit = want ? momentum.byTicker.get(want) : undefined
  if (hit) return hit
  const c = momentum.fresh[0] ?? momentum.continuing[0]
  return c ? momentum.byTicker.get(c.ticker)! : null
}

/** 신호 배지 — 기대 초과 가속 · 가이던스↑n · 어조 a→b */
function SignalBadges({ c }: { c: CallMomentumCandidate }) {
  const up = raisedGuidance(c)
  return <>
    {c.accel?.on && <Badge variant="outline" className="border-up/40 font-normal text-up">기대 초과 가속</Badge>}
    {up > 0 && <Badge variant="outline" className="font-normal">가이던스↑ {up}</Badge>}
    {toneUp(c) && <Badge variant="outline" className="border-hypothesis/40 font-normal text-hypothesis">어조 {c.prev_tone}→{c.tone}</Badge>}
  </>
}

function Reaction({ r }: { r: SeasonItem | undefined }) {
  if (!r || r.d1 == null) return <span className="text-caption text-muted-foreground">반응 집계 전</span>
  return <span className="text-caption text-muted-foreground">첫 거래일 <Pp v={r.d1} />{r.latest != null && r.latest !== r.d1 && <> → <Pp v={r.latest} /></>}</span>
}

export function MomentumBoard({ query, d, momentum }: { query: MomentumQuery; d: SeasonOverview; momentum: MomentumSet }) {
  const [, setParams] = useSearchParams()
  const picked = usePicked(momentum)
  const reported = new Map(d.reported.map((r) => [r.ticker, r]))
  const core = new Map(d.core.tickers.map((t) => [t.ticker, t.reasons]))
  const pick = (t: string) => setParams((p) => patchParams(p, { pick: t }), { replace: true, preventScrollReset: true })
  return (
    <Section className="min-w-0">
      <div id="momentum" className="scroll-mt-20" />
      <QueryState query={query} loading={<Skeleton className="h-80 w-full rounded-card" />} isEmpty={() => false}>{(m) => {
        const total = momentum.fresh.length + momentum.continuing.length
        const history = m.history.filter((h) => h.key !== d.season.key)
        const cov = m.coverage
        return <div className="flex flex-col gap-3">
          <h2 className="flex items-center gap-1 text-[15px] font-semibold">
            새 모멘텀 후보
            <InfoTip label="새 모멘텀 후보 설명">
              직전 분기보다 매출 성장이 빨라지며 기대를 넘었거나(기대 초과 가속), 성장 가이던스를 올렸거나, 수요 어조가 높아진 회사입니다. 직전 분기에도 후보였으면 '이어지는 모멘텀'으로 따로 둡니다. 인용은 원문 대조를 통과한 것만 씁니다.
              대상 {cov.universe}개사 · 보도자료 {cov.with_releases} · 컨콜 {cov.with_transcripts} · 분기 비교 가능 {cov.comparable}. 매일 07:20 판정, 월요일 07:10 텔레그램.
            </InfoTip>
            <span className="tabular-nums font-normal text-muted-foreground">{total}</span>
          </h2>
          {!m.sec_configured && <div role="alert" className="flex gap-2 border border-chart-warning/40 bg-chart-warning/10 p-3 text-sm">
            <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-chart-warning" />
            <span>SEC 실적 보도자료 수집이 멈춰 있습니다. <code>.env</code>에 <code>SEC_USER_AGENT="이름 이메일"</code>을 넣어 주세요.</span>
          </div>}

          <H3>새로 붙은 모멘텀 <span className="tabular-nums font-normal text-muted-foreground">{momentum.fresh.length}</span></H3>
          {momentum.fresh.length === 0 ? <Meta>
            {!cov.comparable ? "직전 분기와 비교할 자료가 아직 쌓이는 중입니다."
              : d.counts.reported ? `이번 시즌 실적을 낸 ${d.counts.reported}곳 중 새로 조건을 넘은 곳이 아직 없습니다.`
              : "이번 시즌 실적 발표가 아직 분석되지 않았습니다."}
          </Meta> : (
            <div className="flex flex-col">
              {momentum.fresh.map((c) => {
                const ev = accelLine(c)
                const sel = picked?.c.ticker === c.ticker
                return (
                  <Button key={c.ticker} variant="ghost" onClick={() => pick(c.ticker)} aria-pressed={sel} data-momentum-row={c.ticker}
                    className={cn("grid h-auto w-full grid-cols-[52px_1fr] items-start gap-x-3 rounded-none border-t px-1 py-2.5 text-left font-normal whitespace-normal first:border-t-0", sel && "bg-muted")}>
                    <span className="flex flex-col">
                      <span className="font-mono text-sm font-semibold">{c.ticker}</span>
                      <span className="text-caption text-muted-foreground">점수 {c.score.toFixed(0)}</span>
                    </span>
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="flex flex-wrap items-center gap-1">
                        <SignalBadges c={c} /><CoreBadge core={core.get(c.ticker)} />
                        <span className="ml-auto"><Reaction r={reported.get(c.ticker)} /></span>
                      </span>
                      {ev.text && <span className="line-clamp-1 text-caption">
                        {ev.kind === "quote" && <Badge variant="secondary" className="mr-1 font-normal">원문</Badge>}
                        {ev.kind === "quote" ? `“${ev.text}”` : ev.text}
                      </span>}
                    </span>
                  </Button>
                )
              })}
            </div>
          )}

          {momentum.continuing.length > 0 && (
            <Collapsible defaultOpen className="border-t pt-3">
              <div className="flex items-center justify-between">
                <H3>이어지는 모멘텀 <span className="tabular-nums font-normal text-muted-foreground">{momentum.continuing.length}</span></H3>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="xs" className="group text-muted-foreground">
                    <span className="group-data-[state=open]:hidden">펼치기</span><span className="hidden group-data-[state=open]:inline">접기</span>
                    <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />
                  </Button>
                </CollapsibleTrigger>
              </div>
              <CollapsibleContent className="flex flex-wrap gap-1.5 pt-2">
                {momentum.continuing.map((c) => {
                  const r = reported.get(c.ticker)
                  return (
                    <Button key={c.ticker} variant="outline" size="xs" onClick={() => pick(c.ticker)} aria-pressed={picked?.c.ticker === c.ticker}
                      className={cn("rounded-none font-normal", picked?.c.ticker === c.ticker && "bg-muted")} title={c.name ?? c.ticker}>
                      <span className="font-mono font-semibold">{c.ticker}</span>
                      {c.accel?.on && <span className="size-1.5 rounded-full bg-up" aria-label="가속" />}
                      <span className="tabular-nums text-muted-foreground">{c.score.toFixed(0)}</span>
                      {r?.d1 != null && <Pp v={r.d1} />}
                    </Button>
                  )
                })}
              </CollapsibleContent>
            </Collapsible>
          )}

          {history.length > 0 && (
            <Collapsible className="border-t pt-2">
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="group w-full justify-between text-muted-foreground">
                  <span>지난 시즌 기록 <span className="tabular-nums">{history.length}</span></span>
                  <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="space-y-2 pt-2">
                {history.map((h) => <Collapsible key={h.key}>
                  <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="w-full justify-between">
                    <span>{h.label} <span className="font-normal text-muted-foreground">· {h.candidates.length}건</span></span>
                    <ChevronDown aria-hidden="true" className="size-4" /></Button></CollapsibleTrigger>
                  <CollapsibleContent className="space-y-3 pt-2">{h.candidates.map((c) => <CandidateCard key={`${c.ticker}-${c.event_date}`} c={c} />)}</CollapsibleContent>
                </Collapsible>)}
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      }}</QueryState>
    </Section>
  )
}

/* ---------- 선택한 후보 상세 (전체 폭) ---------- */
export function PickedCandidate({ d, momentum }: { d: SeasonOverview; momentum: MomentumSet }) {
  const picked = usePicked(momentum)
  if (!picked) return null
  const { c, kind } = picked
  const r = d.reported.find((x) => x.ticker === c.ticker)
  const reasons = d.core.tickers.find((t) => t.ticker === c.ticker)?.reasons
  const a = c.accel
  const numeric = a?.basis === "numeric" ? a : null
  const growth = c.drivers.filter((x) => x.status === "new" || x.status === "accelerating").slice(0, 3)
  const guide = c.guidance.filter((g) => g.direction === "raised" || g.direction === "lowered" || g.direction === "initiated")
  const quoteAccel = a?.on && a.basis === "quote" && a.quote ? a.quote : null
  return (
    <Section className="min-w-0">
      <div id="momentum-pick" data-picked={c.ticker} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h2 className="text-lg font-semibold">{c.name ?? c.ticker}</h2>
          <span className="text-caption text-muted-foreground">{c.ticker} · {mmdd(c.event_date)} 실적 발표 · 점수 {c.score.toFixed(0)}</span>
          <span className="ml-auto text-caption text-muted-foreground">선택한 후보</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className={cn("font-normal", kind === "new" ? "border-up/40 text-up" : "")}>{kind === "new" ? "새로 붙은 모멘텀" : "이어지는 모멘텀"}</Badge>
          <SignalBadges c={c} />
          {r?.d1 != null && <span className="text-sm">첫 거래일 <Pp v={r.d1} className="font-semibold" /></span>}
          {r?.latest != null && <span className="text-sm">최근 <Pp v={r.latest} className="font-semibold" /></span>}
          {r && <span className="text-caption text-muted-foreground">{r.sector_name}</span>}
          <CoreBadge core={reasons} />
        </div>
        <div className="grid grid-cols-2 gap-px border bg-border md:grid-cols-4">
          <Cell label="매출 성장(전년 대비)" value={numeric ? `${formatPercent(numeric.g_prev)} → ${formatPercent(numeric.g_now)}` : "-"} strong />
          <Cell label="직전 분기 대비" value={numeric ? formatPp(numeric.gap, 1) : "-"} />
          <Cell label="성장 가이던스" value={raisedGuidance(c) ? `상향 ${raisedGuidance(c)}건` : c.guidance.some((g) => g.direction === "lowered") ? "하향 있음" : "-"} />
          <Cell label="수요 어조" value={c.tone != null ? `${c.prev_tone ?? "-"} → ${c.tone}` : "-"} />
        </div>
        {quoteAccel && <p className="text-sm"><Badge variant="secondary" className="mr-1 font-normal">원문</Badge>“{quoteAccel}”</p>}
        {c.summary && <div className="bg-muted/50 px-3 py-2.5">
          <p className="text-caption text-hypothesis">AI 요약 · 아래 근거로 작성</p>
          <p className="mt-1 text-sm leading-relaxed">{c.summary}</p>
        </div>}
        {r?.headline && <p className="text-sm"><span className="text-muted-foreground">시장 반응 · </span>{r.headline}</p>}
        {growth.length > 0 && <ul className="flex flex-col gap-2">{growth.map((x) => (
          <li key={x.name} className="space-y-1">
            <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
              <Badge variant="outline" className={`text-caption ${STATUS[x.status as keyof typeof STATUS].cls}`}>{STATUS[x.status as keyof typeof STATUS].label}</Badge>
              {x.name}{x.magnitude && <span className="text-caption font-normal text-muted-foreground">{x.magnitude}</span>}
            </p>
            <blockquote className="border-l-2 pl-3 text-caption text-muted-foreground">“{x.quote}” — {SOURCE[x.source] ?? x.source}</blockquote>
          </li>
        ))}</ul>}
        {guide.length > 0 && <p className="text-sm">
          <span className="text-muted-foreground">가이던스 · </span>
          {guide.slice(0, 6).map((g, i) => <span key={g.metric + i}>{i > 0 && " · "}
            <span className={g.direction === "raised" ? "text-up" : g.direction === "lowered" ? "text-down" : ""}>{GUIDE[g.direction]}</span> {g.metric}</span>)}
          {guide.length > 6 && <span className="text-muted-foreground"> 외 {guide.length - 6}</span>}
        </p>}
        {c.qa_focus.length > 0 && <p className="text-caption text-muted-foreground">애널리스트 질문 초점 · {c.qa_focus.join(" · ")}</p>}
        <div className="flex flex-wrap gap-2 pt-1">
          <WatchAdd ticker={c.ticker} />
          <Button variant="outline" size="sm" asChild><Link to={`/discover?code=${encodeURIComponent(c.ticker)}&market=us`}>종목 발견에서 차트·조건 보기</Link></Button>
          {r?.transcript_id && <Button variant="outline" size="sm" asChild><Link to={`/follow/transcripts?t=${r.transcript_id}`}>콜 상세 →</Link></Button>}
          <Button variant="ghost" size="sm" asChild>
            <Link to={`/chat?q=${encodeURIComponent(`${c.name ?? c.ticker}(${c.ticker})의 이번 실적에서 모멘텀 근거를 정리해 주세요`)}`}><MessageSquare /> 이 종목으로 대화</Link>
          </Button>
        </div>
      </div>
    </Section>
  )
}

function Cell({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex flex-col gap-1 bg-card p-3">
      <span className="text-caption text-muted-foreground">{label}</span>
      <span className={cn("font-mono tabular-nums", strong ? "text-lg font-semibold" : "text-base")}>{value}</span>
    </div>
  )
}

/** 관심 종목에 추가 — 기본 관심 묶음(미국 티커 포함). 이미 있으면 상태만 보인다 */
function WatchAdd({ ticker }: { ticker: string }) {
  const group = useDefaultWatchGroup()
  const toggle = useToggleWatch()
  const watched = !!group.data?.members.some((m) => m.stock_code === ticker)
  return (
    <Button size="sm" disabled={!group.data || watched || toggle.isPending}
      onClick={() => toggle.mutate({ stockCode: ticker, watched: true }, {
        onSuccess: (g) => toast.success(`‘${g.name}’에 ${ticker}를 추가했습니다`),
        onError: (e) => toast.error(e instanceof Error && e.message ? e.message : "관심 종목에 추가하지 못했습니다"),
      })}>
      {watched ? "관심 종목에 있음" : "관심 종목에 추가"}
    </Button>
  )
}
