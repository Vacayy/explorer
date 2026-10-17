import { Link, useSearchParams } from "react-router-dom"
import { Check } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import MultiLineChart from "@/components/charts/MultiLineChart"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { SparkLine } from "@/components/shared/Spark"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { useChartPalette } from "@/hooks/useChartPalette"
import { useTrendLeaders } from "@/hooks/useTrendLeaders"
import { cn } from "@/lib/utils"
import { formatKrw, formatKstDateTime, formatLevel, formatNumber, formatPercent } from "@/utils/format"
import type { TrendEvent, TrendEventKind, TrendLeader } from "@/types"
import type { WidgetBodyProps, WidgetMeta } from "./types"

/**
 * 가파른 추세 위젯 (pipeline/trend_leaders, docs/specs/home-widgets.md §3).
 * 탭: 추세(조건 모두 통과) | 신고가·매물대(52주 신고가 돌파 · 매물대 돌파 후 지지). 탭은 URL trend_tab,
 * 종목을 누르면 근거 창(URL trend=<코드>) — 조건별 실제 값과 120일 차트(MA20·MA60·60일 회귀선).
 */

export const EVENT_LABEL: Record<TrendEventKind, string> = { high52: "52주 신고가", vp_retest: "매물대 지지" }
const olderThan = (iso: string | null | undefined, days: number) =>
  !!iso && Date.now() - new Date(iso.slice(0, 10) + "T00:00:00").getTime() > (days + 1) * 86_400_000
const won = (v: number) => formatNumber(Math.round(v))
const COLS_WIDE = "grid-cols-[minmax(0,1fr)_64px_52px_40px_40px_48px]"
const COLS_NARROW = "grid-cols-[minmax(0,1fr)_56px_52px]"

export function useTrendMeta(): WidgetMeta {
  const q = useTrendLeaders()
  return { asOf: q.data?.as_of ?? null, stale: olderThan(q.data?.as_of, 4) }
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
  return <div className="flex h-full flex-col gap-2">
    <div className="flex flex-wrap items-center gap-2">
      <SegmentTabs value={tab} onChange={v => set("trend_tab", v === "trend" ? null : v)}
        tabs={[{ value: "trend", label: `추세 ${formatNumber(d.passed)}` }, { value: "events", label: `신고가·매물대 ${formatNumber(d.events.length)}` }]} />
      <span className="ml-auto text-[11px] text-muted-foreground" title="계산에 쓴 시세의 마지막 수집 시각 — 평일 16:35 수집, 20:20 재수집">
        시세 {formatKstDateTime(d.computed_from ? d.computed_from.replace(" ", "T") + "Z" : null)} 수집분
      </span>
    </div>
    <div className="min-h-0 flex-1">
      {tab === "trend"
        ? <TrendList items={d.items} universe={d.universe} passed={d.passed} criteria={d.criteria} wide={w >= 6} short={h <= 3} onPick={code => set("trend", code)} />
        : <EventList events={d.events} short={h <= 3} />}
    </div>
    <TrendEvidenceDialog item={picked} criteria={d.criteria} onClose={() => set("trend", null)} />
  </div>
}

function TrendList({ items, universe, passed, criteria, wide, short, onPick }: {
  items: TrendLeader[]; universe: number; passed: number; criteria: string; wide: boolean; short: boolean; onPick: (code: string) => void
}) {
  if (!items.length) return <WidgetState empty emptyText={`조건을 모두 통과한 종목이 없어요. (${criteria})`} />
  const fresh = items.filter(i => i.new).length
  return <div className="flex h-full flex-col gap-1.5">
    <p className="text-[12px] text-muted-foreground" title={criteria}>
      시총 3,000억+ {formatNumber(universe)}종목 중 <span className="font-medium text-foreground">{formatNumber(passed)}</span>개
      {fresh > 0 && <> · 5거래일 새 진입 {formatNumber(fresh)}</>} · 누르면 근거
    </p>
    <div className={cn("grid items-center gap-x-3 border-b px-1 pb-1 text-[11px] text-muted-foreground", wide ? COLS_WIDE : COLS_NARROW)}>
      <span>종목</span><span>60일</span><span className="text-right">수익률</span>
      {wide && <><span className="text-right" title="60거래일 log 가격 회귀의 R² — 1에 가까울수록 고르게 올랐다">고름</span>
        <span className="text-right" title="ADX(14) — 추세 강도">ADX</span>
        <span className="text-right" title="20일 이동평균 대비 — 클수록 단기 과열">이격</span></>}
    </div>
    <ul className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2 text-[13px]">
      {items.slice(0, short ? 4 : items.length).map(t => (
        <li key={t.stock_code}>
          <Button variant="ghost" onClick={() => onPick(t.stock_code)} aria-label={`${t.name} 추세 근거 보기`}
            className={cn("grid h-auto w-full items-center gap-x-3 rounded-sm px-1 py-1 text-left text-[13px] font-normal", wide ? COLS_WIDE : COLS_NARROW)}>
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-medium">{t.name}</span>
              {t.new && <Badge variant="outline" className="shrink-0 px-1 text-[10px] text-primary">신규</Badge>}
              {t.events.map(k => <Badge key={k} variant="secondary" className="shrink-0 px-1 text-[10px]">{EVENT_LABEL[k]}</Badge>)}
              {wide && t.sector && <span className="truncate text-[11px] text-muted-foreground">{t.sector}</span>}
            </span>
            <SparkLine data={t.spark} height={18} />
            <span className="text-right tabular-nums text-up">{formatPercent(t.ret_60)}</span>
            {wide && <><span className="text-right tabular-nums text-muted-foreground">{formatLevel(t.r2)}</span>
              <span className="text-right tabular-nums text-muted-foreground">{formatNumber(Math.round(t.adx))}</span>
              <span className={cn("text-right tabular-nums", t.gap_ma20 >= 15 ? "text-chart-warning" : "text-muted-foreground")}>{formatPercent(t.gap_ma20)}</span></>}
          </Button>
        </li>
      ))}
    </ul>
  </div>
}

function EventList({ events, short }: { events: TrendEvent[]; short: boolean }) {
  if (!events.length) return <WidgetState empty emptyText="최근 52주 신고가 돌파·매물대 돌파 후 지지 종목이 없어요." />
  return <ul className="-mr-2 h-full divide-y overflow-y-auto pr-2 text-[13px]">
    {events.slice(0, short ? 4 : events.length).map(e => (
      <li key={`${e.kind}-${e.stock_code}`}>
        <Link to={`/analyze/${e.stock_code}/summary?scan=1`} title={`${e.name} 기술적 분석 열기`} className="block space-y-0.5 rounded-sm px-1 py-1.5 hover:bg-muted/50">
          <span className="flex items-center gap-1.5">
            <Badge variant={e.kind === "high52" ? "default" : "secondary"} className="shrink-0 px-1 text-[10px]">{EVENT_LABEL[e.kind]}</Badge>
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
  const palette = useChartPalette(4)
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
  const fitFrom = e ? e.dates.length - 61 : 0
  const data = e ? e.dates.map((time, i) => ({
    time, close: e.closes[i], ma20: e.ma20_series[i], ma60: e.ma60_series[i],
    fit: i >= fitFrom ? e.fit_start * (e.fit_end / e.fit_start) ** ((i - fitFrom) / 60) : null,
  })) : []
  return <Dialog open={!!item} onOpenChange={v => !v && onClose()}>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
      {item && e && <>
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {item.name}
            {item.sector && <span className="text-sm font-normal text-muted-foreground">{item.sector}</span>}
            {item.events.map(k => <Badge key={k} variant="secondary" className="text-[11px]">{EVENT_LABEL[k]}</Badge>)}
          </DialogTitle>
          <DialogDescription>가파른 추세 조건을 모두 통과했습니다 · {criteria}</DialogDescription>
        </DialogHeader>
        <MultiLineChart data={data} height={220} formatValue={won} lines={[
          { key: "close", label: "종가", color: palette[0] ?? "#888", lineWidth: 2 },
          { key: "ma20", label: "MA20", color: palette[1] ?? "#888", lineWidth: 1 },
          { key: "ma60", label: "MA60", color: palette[2] ?? "#888", lineWidth: 1 },
          { key: "fit", label: "60일 회귀선", color: palette[3] ?? "#888", lineWidth: 1, lineStyle: 2 },
        ]} />
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
