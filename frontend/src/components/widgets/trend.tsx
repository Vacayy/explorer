import { Link, useSearchParams } from "react-router-dom"
import { Check } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import MultiLineChart from "@/components/charts/MultiLineChart"
import { WidgetState } from "@/components/shared/WidgetFrame"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { useChartPalette } from "@/hooks/useChartPalette"
import { useTrendChart, useTrendLeaders } from "@/hooks/useTrendLeaders"
import { cn } from "@/lib/utils"
import { formatKrw, formatKstDateTime, formatLevel, formatNumber, formatPercent } from "@/utils/format"
import type { TrendEvent, TrendEventKind, TrendHigh52, TrendLeader } from "@/types"
import type { WidgetBodyProps, WidgetMeta } from "./types"

/**
 * 가파른 추세 위젯 (pipeline/trend_leaders, docs/specs/home-widgets.md §3).
 * 탭: 추세(조건 모두 통과) | 신고가·매물대(52주 신고가 돌파 · 매물대 돌파 후 지지). 탭은 URL trend_tab,
 * 종목을 누르면 근거 창(URL trend=<코드>) — 조건별 실제 값과 2년 차트(MA20·MA60·52주 고점선·60일 회귀선).
 * 추세 종목 중 52주 신고가 단계(돌파 · 돌파 후 지지·재반등)는 배지로 따로 표시하고 URL trend_stage로 골라 본다.
 */

export const EVENT_LABEL: Record<TrendEventKind, string> = { high52: "52주 신고가", vp_retest: "매물대 지지" }
const STAGE: Record<TrendHigh52["kind"], { label: string; variant: "up" | "neutral"; hint: string }> = {
  breakout: { label: "신고가 돌파", variant: "up",
    hint: "최근 5거래일 안에 종가가 직전 250거래일 최고가를 넘었다" },
  retest: { label: "돌파 후 지지", variant: "neutral",
    hint: "60거래일 안 전고점 돌파 → 돌파선 근처(저가 −5%~+3%)까지 되돌림, 종가는 −3% 아래로 안 빠짐 → 다시 올라 지금 돌파선 위" },
}
const StageBadge = ({ s, className }: { s: TrendHigh52; className?: string }) =>
  <Badge variant={STAGE[s.kind].variant} title={`${STAGE[s.kind].label} — ${s.detail}`} className={cn("shrink-0", className)}>{STAGE[s.kind].label}</Badge>
const olderThan = (iso: string | null | undefined, days: number) =>
  !!iso && Date.now() - new Date(iso.slice(0, 10) + "T00:00:00").getTime() > (days + 1) * 86_400_000
const won = (v: number) => formatNumber(Math.round(v))
// 시안 Home-KR 열: 종목 | 업종 | 60일 | 꾸준함 | ADX | 이격 (좁으면 종목 | 60일)
const COLS_WIDE = "grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_64px_48px_40px_48px]"
const COLS_NARROW = "grid-cols-[minmax(0,1fr)_64px]"

export function useTrendMeta(): WidgetMeta {
  const q = useTrendLeaders()
  const d = q.data
  // 시안 Home-KR: 제목 옆 'n종목 중 m'만 — 기준 시각은 묵었을 때만 주의 색으로
  const stale = olderThan(d?.as_of, 4)
  return { asOf: stale ? d?.as_of ?? null : null, stale, sub: d ? `${formatNumber(d.universe)}종목 중 ${formatNumber(d.passed)}` : null }
}

export function TrendBody({ w, h }: WidgetBodyProps) {
  const q = useTrendLeaders()
  const [params, setParams] = useSearchParams()
  const set = (key: string, value: string | null) => setParams(prev => {
    const next = new URLSearchParams(prev)
    if (value == null) next.delete(key); else next.set(key, value)
    return next
  }, { replace: key === "trend_tab", preventScrollReset: true })
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const tab = params.get("trend_tab") === "events" ? "events" : "trend"
  const picked = d.items.find(i => i.stock_code === params.get("trend"))
  // 넓으면(10칸 이상) 탭 없이 좌우로 나란히 — 각 절반이 6칸 폭이라 추세 표도 넓은 열을 쓴다
  const split = w >= 10
  const stamp = <span className="ml-auto text-[11px] text-muted-foreground" title="계산에 쓴 시세의 마지막 수집 시각 — 평일 16:35 수집, 20:20 재수집">
    시세 {formatKstDateTime(d.computed_from ? d.computed_from.replace(" ", "T") + "Z" : null)} 수집분
  </span>
  const stage = params.get("trend_stage")
  const pickedStage = stage === "breakout" || stage === "retest" ? stage : null
  const hasStage = d.items.some(i => i.high52)
  const trendList = <TrendList items={d.items} universe={d.universe} passed={d.passed} criteria={d.criteria} wide={split || w >= 6} short={h <= 3}
    stage={pickedStage} onPick={code => set("trend", code)} events={split ? [] : d.events} />
  const eventList = <EventList events={d.events} short={h <= 3} />
  const stageSeg = hasStage && <SegmentTabs value={pickedStage ?? "all"} onChange={v => set("trend_stage", v === "all" ? null : v)}
    tabs={[{ value: "all", label: "전체" }, { value: "breakout", label: STAGE.breakout.label }, { value: "retest", label: STAGE.retest.label }]} />
  return <div className="flex h-full flex-col gap-3">
    {split ? <>
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-4">
        <section aria-label="추세" className="flex min-h-0 min-w-0 flex-col gap-1.5">
          <h4 className="flex flex-wrap items-center justify-between gap-2 text-[12px] font-medium">추세 {formatNumber(d.passed)}{stageSeg}</h4>
          <div className="min-h-0 flex-1">{trendList}</div>
        </section>
        <section aria-label="신고가·매물대" className="flex min-h-0 min-w-0 flex-col gap-1.5 border-l pl-4">
          <h4 className="flex items-baseline text-[12px] font-medium">신고가·매물대 {formatNumber(d.events.length)}{stamp}</h4>
          <div className="min-h-0 flex-1">{eventList}</div>
        </section>
      </div>
    </> : <>
      {/* 시안 Home-KR: 한 줄 — 왼쪽 탭 · 오른쪽 신고가 단계 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentTabs value={tab} onChange={v => set("trend_tab", v === "trend" ? null : v)}
          tabs={[{ value: "trend", label: `추세 ${formatNumber(d.passed)}` }, { value: "events", label: `신고가·매물대 ${formatNumber(d.events.length)}` }]} />
        {tab === "trend" && stageSeg}
      </div>
      <div className="min-h-0 flex-1">{tab === "trend" ? trendList : eventList}</div>
    </>}
    <TrendEvidenceDialog item={picked} criteria={d.criteria} onClose={() => set("trend", null)} />
  </div>
}

function TrendList({ items: all, universe, passed, criteria, wide, short, stage, onPick, events }: {
  items: TrendLeader[]; universe: number; passed: number; criteria: string; wide: boolean; short: boolean
  stage: TrendHigh52["kind"] | null; onPick: (code: string) => void
  /** 표 아래 '최근 신고가·매물대 이벤트'(시안 Home-KR) — 나란히 보기에서는 오른쪽 칸이 맡아 비운다 */
  events: TrendEvent[]
}) {
  if (!all.length) return <p role="status" className="text-sm text-muted-foreground">오늘은 조건 다섯 개를 모두 통과한 종목이 없습니다. <HowTip criteria={criteria} /></p>
  const items = stage ? all.filter(i => i.high52?.kind === stage) : all.slice(0, 20)   // 상위 20 + 신고가 단계 종목(순위 밖 포함)
  const fresh = all.filter(i => i.new).length
  const num = "text-right font-mono text-[13px] tabular-nums"
  return <div className="flex h-full flex-col gap-2.5">
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <div className={cn("grid items-center gap-x-3 border-b border-line-2 px-2.5 py-2 text-xs font-medium text-ink-3", wide ? COLS_WIDE : COLS_NARROW)}>
        <span>종목</span>{wide && <span>업종</span>}<span className="text-right">60일</span>
        {wide && <><TermTip label="꾸준함" tip="60거래일 종가(로그)에 직선을 그었을 때 그 직선이 가격을 얼마나 잘 설명하는지(R², 0~1). 1에 가까울수록 계단처럼 꾸준히 올랐습니다." />
          <TermTip label="ADX" tip="ADX(14) — 방향과 상관없이 추세가 얼마나 강한지 재는 지표(0~100). 25를 넘으면 뚜렷한 추세로 봅니다." />
          <span className="text-right" title="20일 이동평균 대비 — 클수록 단기 과열">이격</span></>}
      </div>
      <ul className="text-[13px]">
        {items.slice(0, short ? 4 : items.length).map(t => (
          <li key={t.stock_code} className="border-b">
            <Button variant="ghost" onClick={() => onPick(t.stock_code)} aria-label={`${t.name} 추세 근거 보기`}
              className={cn("grid h-auto w-full items-start gap-x-3 rounded-none px-2.5 py-[7px] text-left text-[13px] font-normal", wide ? COLS_WIDE : COLS_NARROW)}>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate font-medium" title={t.name}>{t.name}</span>
                {(t.new || t.high52 || t.events.some(k => k !== "high52")) && <span className="flex flex-wrap gap-1">
                  {t.high52 && <StageBadge s={t.high52} />}
                  {t.new && <Badge className="shrink-0">신규</Badge>}
                  {t.events.filter(k => k !== "high52").map(k => <Badge key={k} variant="up" className="shrink-0">{EVENT_LABEL[k]}</Badge>)}
                </span>}
              </span>
              {wide && <span className="truncate text-ink-2" title={t.sector ?? undefined}>{t.sector ?? "-"}</span>}
              <span className={cn(num, "text-up-ink")}>{formatPercent(t.ret_60)}</span>
              {wide && <><span className={num}>{formatLevel(t.r2)}</span>
                <span className={num}>{t.adx.toFixed(1)}</span>
                <span className={cn(num, t.gap_ma20 >= 15 && "text-warn")}>{formatPercent(t.gap_ma20)}</span></>}
            </Button>
          </li>
        ))}
      </ul>
    </div>
    <p className="shrink-0 text-xs text-ink-3">
      시총 3,000억+ {formatNumber(universe)}종목 중 {formatNumber(passed)}개
      {fresh > 0 && <> · 5거래일 새 진입 {formatNumber(fresh)}</>}
      {' · '}<HowTip criteria={criteria} />
    </p>
    {!short && events.length > 0 && <div className="shrink-0" data-trend-events>
      <span className="text-[11.5px] text-ink-2">최근 신고가·매물대 이벤트</span>
      <ul>{events.slice(0, 4).map(e => (
        <li key={`${e.kind}-${e.stock_code}`} className="border-t first:border-t-0">
          <Link to={`/analyze/${e.stock_code}/summary?scan=1`} title={`${e.name} 기술적 분석 열기`}
            className="grid min-w-0 grid-cols-[auto_auto_minmax(0,1fr)_auto] items-baseline gap-x-3 py-[7px] hover:bg-muted/50 max-sm:grid-cols-[auto_minmax(0,1fr)_auto]">
            <Badge variant="up">{EVENT_LABEL[e.kind]}</Badge>
            <span className="truncate text-[13px]">{e.name}</span>
            <span className="truncate text-xs text-ink-2 max-sm:hidden">{e.detail}{!e.held && <span className="text-warn"> · 지금은 돌파선 아래</span>}</span>
            <span className="font-mono text-[11px] text-ink-3 tabular-nums">{e.date.slice(5).replace("-", "/")}</span>
          </Link>
        </li>
      ))}</ul>
    </div>}
  </div>
}

/** '어떻게 산정되나요?' — 조건 줄은 본문에 쓰지 않고 툴팁으로 (ia-redesign §4.2) */
function HowTip({ criteria }: { criteria: string }) {
  return <Tooltip>
    <TooltipTrigger className="underline decoration-dotted underline-offset-2 hover:text-foreground">어떻게 산정되나요?</TooltipTrigger>
    <TooltipContent className="max-w-[300px] text-xs leading-relaxed">{criteria} · 60거래일 수익률 순 · 종목을 누르면 조건별 실제 값과 차트를 봅니다.</TooltipContent>
  </Tooltip>
}
function TermTip({ label, tip }: { label: string; tip: string }) {
  return <Tooltip>
    <TooltipTrigger className="text-right underline decoration-dotted underline-offset-2">{label}</TooltipTrigger>
    <TooltipContent className="max-w-[260px] text-xs leading-relaxed">{tip}</TooltipContent>
  </Tooltip>
}

function EventList({ events, short }: { events: TrendEvent[]; short: boolean }) {
  if (!events.length) return <WidgetState empty emptyText="최근 52주 신고가 돌파·매물대 돌파 후 지지 종목이 없어요." />
  return <ul className="-mr-2 h-full divide-y overflow-y-auto pr-2 text-[13px]">
    {events.slice(0, short ? 4 : events.length).map(e => (
      <li key={`${e.kind}-${e.stock_code}`}>
        <Link to={`/analyze/${e.stock_code}/summary?scan=1`} title={`${e.name} 기술적 분석 열기`} className="block space-y-0.5 rounded-sm px-1 py-1.5 hover:bg-muted/50">
          <span className="flex items-center gap-1.5">
            <Badge variant="up" className="shrink-0">{EVENT_LABEL[e.kind]}</Badge>
            <span className="truncate font-medium">{e.name}</span>
            {e.sector && <span className="truncate text-[11px] text-muted-foreground">{e.sector}</span>}
            <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground">{e.date.slice(5)} 돌파</span>
          </span>
          <span className="block truncate text-[12px] text-muted-foreground">
            {e.detail}{!e.held && <span className="text-chart-warning"> · 지금은 돌파선 아래</span>}
          </span>
        </Link>
      </li>
    ))}
  </ul>
}

/** 근거 창 — 조건별 실제 값(전부 통과해야 목록에 오른다)과 차트 */
function TrendEvidenceDialog({ item, criteria, onClose }: { item?: TrendLeader; criteria: string; onClose: () => void }) {
  const palette = useChartPalette(5)
  const chart = useTrendChart(item?.stock_code)
  const e = item?.evidence
  const rows = item && e ? [
    { label: "시가총액", rule: "3,000억 이상", value: formatKrw(item.market_cap) },
    { label: "60거래일 수익률", rule: "+30% 이상", value: formatPercent(item.ret_60) },
    { label: "상승의 고름 (log 회귀 R²)", rule: "0.75 이상", value: formatLevel(item.r2) },
    { label: "정배열", rule: "종가 > MA20 > MA60", value: `${won(e.close)} > ${won(e.ma20)} > ${won(e.ma60)}` },
    { label: "MA60 방향", rule: "20거래일 전보다 높음", value: `${won(e.ma60_prev)} → ${won(e.ma60)}` },
    { label: "추세 강도 ADX(14)", rule: "25 이상", value: formatNumber(Math.round(item.adx)) },
    { label: "방향 +DI / −DI", rule: "+DI > −DI", value: `${formatNumber(Math.round(e.plus_di))} > ${formatNumber(Math.round(e.minus_di))}` },
  ] : []
  // 60거래일 회귀선 — 로그 직선이라 가격으로는 지수 곡선
  const c = chart.data
  const fitFrom = c ? c.dates.length - 61 : 0
  const data = c && e ? c.dates.map((time, i) => ({
    time, close: c.closes[i], ma20: c.ma20[i], ma60: c.ma60[i], high52: c.high52[i],
    fit: i >= fitFrom ? e.fit_start * (e.fit_end / e.fit_start) ** ((i - fitFrom) / 60) : null,
  })) : []
  const years = c && c.dates.length ? (new Date(c.dates.at(-1)!).getTime() - new Date(c.dates[0]).getTime()) / (365.25 * 86_400_000) : 0
  return <Dialog open={!!item} onOpenChange={v => !v && onClose()}>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
      {item && e && <>
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {item.name}
            {item.sector && <span className="text-sm font-normal text-muted-foreground">{item.sector}</span>}
            {item.high52 && <StageBadge s={item.high52} className="px-1.5 text-[11px]" />}
            {item.events.filter(k => k !== "high52").map(k => <Badge key={k} variant="secondary" className="text-[11px]">{EVENT_LABEL[k]}</Badge>)}
          </DialogTitle>
          <DialogDescription>가파른 추세 조건을 모두 통과했습니다 · {criteria}</DialogDescription>
        </DialogHeader>
        {item.high52 && <p className="text-sm"><span className="font-medium">{STAGE[item.high52.kind].label}</span> · {item.high52.detail}</p>}
        {chart.isPending ? <Skeleton className="h-[260px] w-full rounded-card" />
          : chart.isError || !data.length ? <p className="py-10 text-center text-sm text-muted-foreground">차트를 불러오지 못했습니다.</p>
          : <>
            <MultiLineChart data={data} height={260} formatValue={won} lines={[
              { key: "close", label: "종가", color: palette[0] ?? "#888", lineWidth: 2 },
              { key: "ma20", label: "MA20", color: palette[1] ?? "#888", lineWidth: 1 },
              { key: "ma60", label: "MA60", color: palette[2] ?? "#888", lineWidth: 1 },
              { key: "high52", label: "52주 고점선", color: palette[4] ?? "#888", lineWidth: 1, lineStyle: 2 },
              { key: "fit", label: "60일 회귀선", color: palette[3] ?? "#888", lineWidth: 1, lineStyle: 2 },
            ]} />
            <p className="-mt-2 text-caption text-muted-foreground">
              최근 {formatNumber(c!.dates.length)}거래일({years.toFixed(1)}년){years < 1.9 && " — 저장된 시세가 여기까지"} · 52주 고점선 = 그날의 직전 250거래일 최고가(넘으면 신고가)
            </p>
          </>}
        <Table>
          <TableHeader><TableRow><TableHead>조건</TableHead><TableHead>기준</TableHead><TableHead className="text-right">실제</TableHead><TableHead className="w-8" /></TableRow></TableHeader>
          <TableBody>
            {rows.map(r => <TableRow key={r.label}>
              <TableCell>{r.label}</TableCell>
              <TableCell className="text-muted-foreground">{r.rule}</TableCell>
              <TableCell className="text-right tabular-nums">{r.value}</TableCell>
              <TableCell><Check className="size-4 text-chart-green" aria-label="통과" /></TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
        <p className="text-caption text-muted-foreground">
          20거래일 수익률 {formatPercent(item.ret_20)} · MA20 이격 {formatPercent(item.gap_ma20)}{item.gap_ma20 >= 15 && " (단기 과열 구간)"}
          {item.new ? " · 5거래일 전에는 조건 밖이었다(새 진입)" : ""}. 일봉 종가 기준이며 매매 신호가 아닙니다.
        </p>
        <div className="flex justify-end">
          <Button asChild size="sm"><Link to={`/analyze/${item.stock_code}/summary?scan=1`}>기술적 분석 열기</Link></Button>
        </div>
      </>}
    </DialogContent>
  </Dialog>
}
