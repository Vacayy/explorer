import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { SparkLine } from "@/components/shared/Spark"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { EVENT_KIND, dday } from "@/components/portfolio/EventsCard"
import { useDefaultWatchGroup, useGroupDigests, useGroupSignals } from "@/hooks/useGroups"
import { usePortfolio, usePortfolioEvents, usePortfolioExposure, usePortfolioFlow, usePortfolioHistory } from "@/hooks/usePortfolio"
import { cn } from "@/lib/utils"
import { formatPercent, formatRatio } from "@/utils/format"
import type { PortfolioSummary } from "@/types"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/**
 * 포트폴리오 위젯 6종 (docs/specs/home-widgets.md §2·§6) — 비율·날짜만(D-212). 모두 캐시된 GET만 읽는다:
 * /api/portfolio는 저장된 시세만 읽고(갱신은 포트폴리오 화면의 POST), 묶음 요약도 생성 없이 읽기만 한다.
 */

const tone = (v: number | null | undefined) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up" : "text-down"
const noLedger = (d: PortfolioSummary) => !d.holdings.length && d.cash_weight_pct == null
/** 기준 시각 = 장중 시세 시각 또는 종가일 */
const quoteAsOf = (d?: PortfolioSummary) => d?.quoted_at ? `장중 ${d.quoted_at.slice(5, 10)} ${d.quoted_at.slice(11, 16)}` : d?.as_of ?? null

/* ── 포트폴리오 오늘 ── */
function useTodayMeta(): WidgetMeta {
  const q = usePortfolio()
  return { asOf: quoteAsOf(q.data) }
}
function TodayBody({ h }: WidgetBodyProps) {
  const q = usePortfolio()
  const history = usePortfolioHistory(!!q.data?.quoted_at)
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (noLedger(d)) return <WidgetState empty emptyText="기록된 거래가 없어요. 포트폴리오에서 거래를 입력하면 계산합니다." />
  const points = (history.data ?? []).map(p => p.cum_return_pct)
  return <div className="flex h-full flex-col gap-1.5">
    <WidgetHero value={<span className={tone(d.day_return_pct)}>{formatPercent(d.day_return_pct)}</span>} aside={<span className="text-sm text-muted-foreground">오늘</span>} />
    <p className="text-[13px] text-muted-foreground">누적 <span className={cn("font-medium tabular-nums", tone(d.total_return_pct))}>{formatPercent(d.total_return_pct)}</span>
      <span className="mx-1">·</span>현금 <span className="font-medium tabular-nums text-foreground">{formatRatio(d.cash_weight_pct)}</span></p>
    {h > 2 && points.length >= 2 && <div className="mt-auto"><SparkLine data={points} height={Math.max(28, (h - 2) * 40)} /></div>}
  </div>
}

/* ── 다가오는 일정 ── */
function EventsBody({ h }: WidgetBodyProps) {
  const q = usePortfolioEvents()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const [next, ...rest] = q.data
  if (!next) return <WidgetState empty emptyText="45일 안에 확인된 보유 종목 일정이 없어요. 평일 16:50에 갱신합니다." />
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={dday(next.date)} aside={<span className="min-w-0 truncate text-sm text-muted-foreground">{next.title}{next.estimated ? " (예상)" : ""}</span>} />
    {h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rest.slice(0, h > 3 ? 5 : 2).map(e => (
        <li key={`${e.date}-${e.kind}-${e.title}`} className="flex items-center gap-2 py-1.5">
          <span className="w-10 shrink-0 tabular-nums text-muted-foreground">{dday(e.date)}</span>
          <span className="min-w-0 flex-1 truncate">{e.title}</span>
          <Badge variant={e.estimated ? "outline" : "secondary"} className="shrink-0 text-[11px] font-normal">{e.estimated ? "예상" : EVENT_KIND[e.kind] ?? e.kind}</Badge>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 공통 변수 노출 ── */
const DIRECTION: Record<string, string> = { "+": "수혜 요인", "−": "부담 요인", "+−": "영향 엇갈림" }
function ExposureBody({ h }: WidgetBodyProps) {
  const q = usePortfolioExposure()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const [top] = q.data.drivers
  if (!top) return <WidgetState empty emptyText="보유 종목이 함께 기대는 변수의 근거가 아직 없어요." />
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={formatRatio(top.exposure_pct)} aside={<span className="min-w-0 truncate text-sm text-muted-foreground">{top.name}{top.direction ? ` · ${DIRECTION[top.direction] ?? ""}` : ""}</span>} />
    {h > 2 && <ul className="min-h-0 space-y-1.5 overflow-hidden text-[13px]">
      {q.data.drivers.slice(0, 3).map(d => (
        <li key={d.key} className="grid grid-cols-[minmax(0,1fr)_88px_44px] items-center gap-2">
          <span className="truncate">{d.name}</span>
          <Progress value={d.exposure_pct} aria-label={`${d.name} 노출 ${formatRatio(d.exposure_pct)}`} className="h-1.5" />
          <span className="text-right tabular-nums">{formatRatio(d.exposure_pct)}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 보유 종목 자료 흐름 ── */
function useFlowMeta(): WidgetMeta {
  const q = usePortfolioFlow()
  return { asOf: q.data?.find(f => f.series.length)?.series.at(-1)?.date ?? null }
}
function FlowBody({ h }: WidgetBodyProps) {
  const q = usePortfolioFlow()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!q.data.length) return <WidgetState empty emptyText="보유 종목이 없어요." />
  const surge = q.data.filter(f => f.surge).length
  const turned = q.data.filter(f => f.tone_shift).length
  const rows = [...q.data].sort((a, b) => Number(b.surge || b.tone_shift) - Number(a.surge || a.tone_shift) || b.today - a.today)
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${surge + turned}건`} aside={<span className="text-sm text-muted-foreground">언급 급증 {surge} · 부정 전환 {turned}</span>} />
    {h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rows.slice(0, h > 3 ? 5 : 3).map(f => (
        <li key={f.code} className="flex items-center gap-2 py-1.5">
          <Link to={`/analyze/${f.code}/mentions`} className="min-w-0 flex-1 truncate hover:underline">{f.name}</Link>
          {f.surge && <Badge variant="outline" className="shrink-0 border-hypothesis/40 text-[11px] text-hypothesis">급증</Badge>}
          {f.tone_shift && <Badge variant="outline" className="shrink-0 border-down/40 text-[11px] text-down">부정 {f.neg_prev_pct}%→{f.neg_today_pct}%</Badge>}
          <span className="w-14 shrink-0 text-right tabular-nums text-muted-foreground">오늘 {f.today}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 묶음 오늘 신호 (기본 관심 묶음) ── */
function useSignalsMeta(): WidgetMeta {
  const g = useDefaultWatchGroup()
  return { asOf: g.data?.last_as_of ?? null, stale: !!g.data?.evaluation_pending }
}
function SignalsBody({ h }: WidgetBodyProps) {
  const g = useDefaultWatchGroup()
  const s = useGroupSignals(g.data?.id ?? null, 1)
  if (!g.data || !s.data) return <WidgetState loading={g.isLoading || s.isLoading} error={g.isError || s.isError}
    onRetry={() => { void g.refetch(); void s.refetch() }} />
  const ruleCount = g.data.rules.default.length + Object.values(g.data.rules.members).reduce((n, r) => n + r.length, 0)
  if (!ruleCount) return <WidgetState empty emptyText={`'${g.data.name}' 묶음에 감시 조건이 없어요. 종목 묶음에서 조건을 정하면 매일 평가합니다.`} />
  const items = s.data
  return <div className="flex h-full flex-col gap-2">
    {g.data.evaluation_pending && <p className="text-[11px] text-chart-warning">최신 거래일({g.data.latest_trade_date ?? "-"}) 평가 전이에요.</p>}
    <WidgetHero value={`${items.length}개`} aside={<span className="truncate text-sm text-muted-foreground">새 신호 · {g.data.name}</span>} />
    {!items.length ? <p className="text-[13px] text-muted-foreground">조건을 새로 통과한 종목이 없어요.</p>
      : h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
        {items.slice(0, h > 3 ? 5 : 3).map(x => (
          <li key={`${x.stock_code}-${x.rule_id}`} className="flex items-center justify-between gap-2 py-1.5">
            <Link to={`/analyze/${x.stock_code}/summary`} className="min-w-0 truncate font-medium hover:underline">{x.name ?? x.stock_code}</Link>
            <span className="shrink-0 truncate text-muted-foreground">{x.label}</span>
          </li>
        ))}
      </ul>}
  </div>
}

/* ── 관심 종목 오늘 요약 (기본 관심 묶음의 최신 1D 요약) ── */
function useDigestsMeta(): WidgetMeta {
  const g = useDefaultWatchGroup()
  const q = useGroupDigests(g.data?.id ?? null)
  return { asOf: q.data?.as_of ?? null }
}
function DigestsBody({ h }: WidgetBodyProps) {
  const g = useDefaultWatchGroup()
  const q = useGroupDigests(g.data?.id ?? null)
  if (!g.data || !q.data) return <WidgetState loading={g.isLoading || q.isLoading} error={g.isError || q.isError}
    onRetry={() => { void g.refetch(); void q.refetch() }} />
  const items = q.data.items
  if (!items.length) return <WidgetState empty emptyText="최근 7일 관심 종목의 1일 요약이 없어요. 새 자료가 쌓인 날 만들어집니다." />
  const latest = items.filter(i => i.date === q.data!.as_of).length
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${latest}종목`} aside={<span className="text-sm text-muted-foreground">1일 요약 · {g.data.name}</span>} />
    <ul className="min-h-0 space-y-2 overflow-hidden text-[13px]">
      {items.slice(0, h > 3 ? 3 : h > 2 ? 2 : 1).map(i => (
        <li key={i.code} className="min-w-0">
          <p className="flex items-baseline gap-1.5"><Link to={`/analyze/${i.code}/mentions`} className="truncate font-medium hover:underline">{i.name}</Link>
            <span className="shrink-0 text-[11px] text-muted-foreground">{i.date.slice(5)}{i.docs != null ? ` · 자료 ${i.docs}건` : ""}</span></p>
          <p className="line-clamp-2 leading-5 text-muted-foreground">{i.insights ?? i.lead ?? "-"}</p>
        </li>
      ))}
    </ul>
  </div>
}

/** registry.tsx가 이 배열을 그대로 펼친다 */
export const PORTFOLIO_WIDGETS: WidgetDef[] = [
  { id: "portfolio.today", title: "포트폴리오 오늘", description: "오늘 수익률 · 누적 시간가중 수익률 · 현금 비중 · 누적 추이", section: "portfolio", group: "포트폴리오",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/portfolio", useMeta: useTodayMeta, Body: TodayBody },
  { id: "portfolio.events", title: "다가오는 일정", description: "보유 종목 다음 일정 D-day · 45일 목록(확정·예상)", section: "portfolio", group: "포트폴리오",
    size: { w: 4, h: 4, minW: 3, minH: 2 }, detailPath: "/portfolio/events", useMeta: () => ({ asOf: null }), Body: EventsBody },
  { id: "portfolio.exposure", title: "공통 변수 노출", description: "보유 종목이 함께 기대는 변수 · 걸린 비중 상위 3", section: "portfolio", group: "포트폴리오",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/portfolio", useMeta: useTodayMeta, Body: ExposureBody },
  { id: "portfolio.flow", title: "보유 종목 자료 흐름", description: "언급 급증 · 부정 전환 종목과 오늘 언급 수", section: "portfolio", group: "포트폴리오",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/portfolio/holdings", useMeta: useFlowMeta, Body: FlowBody },
  { id: "watch.signals", title: "묶음 오늘 신호", description: "기본 관심 묶음에서 감시 조건을 새로 통과한 종목", section: "portfolio", group: "관심",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/follow/stocks", useMeta: useSignalsMeta, Body: SignalsBody },
  { id: "watch.digests", title: "관심 종목 오늘 요약", description: "기본 관심 묶음 종목의 최신 1일 자료 요약", section: "portfolio", group: "관심",
    size: { w: 4, h: 4, minW: 3, minH: 2 }, detailPath: "/follow/stocks", useMeta: useDigestsMeta, Body: DigestsBody },
]
