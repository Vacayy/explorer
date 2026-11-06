import { Link } from "react-router-dom"
import { Check } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import MultiLineChart from "@/components/charts/MultiLineChart"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { useChartPalette } from "@/hooks/useChartPalette"
import { useTrendChart } from "@/hooks/useTrendLeaders"
import { cn } from "@/lib/utils"
import { formatKrw, formatLevel, formatNumber, formatPercent } from "@/utils/format"
import type { TrendEvent, TrendEventKind, TrendHigh52, TrendLeader } from "@/types"

/**
 * 가파른 추세 조각 (pipeline/trend_leaders, docs/specs/home-widgets.md §2) — 홈 › 한국 시장 ③ 칸(home/MarketKr TrendCard)이 쓴다.
 * 신고가·매물대 목록(EventList)과 근거 창(TrendEvidenceDialog — 조건별 실제 값과 2년 차트: MA20·MA60·52주 고점선·60일 회귀선).
 * 추세 종목 중 52주 신고가 단계(돌파 · 돌파 후 지지·재반등)는 배지(StageBadge)로 표시한다.
 */

export const EVENT_LABEL: Record<TrendEventKind, string> = { high52: "52주 신고가", vp_retest: "매물대 지지" }
const STAGE: Record<TrendHigh52["kind"], { label: string; variant: "up" | "neutral"; hint: string }> = {
  breakout: { label: "신고가 돌파", variant: "up",
    hint: "최근 5거래일 안에 종가가 직전 250거래일 최고가를 넘었다" },
  retest: { label: "돌파 후 지지", variant: "neutral",
    hint: "60거래일 안 전고점 돌파 → 돌파선 근처(저가 −5%~+3%)까지 되돌림, 종가는 −3% 아래로 안 빠짐 → 다시 올라 지금 돌파선 위" },
}
export const StageBadge = ({ s, className }: { s: TrendHigh52; className?: string }) =>
  <Badge variant={STAGE[s.kind].variant} title={`${STAGE[s.kind].label} — ${s.detail}`} className={cn("shrink-0", className)}>{STAGE[s.kind].label}</Badge>
const won = (v: number) => formatNumber(Math.round(v))
export function EventList({ events, short }: { events: TrendEvent[]; short: boolean }) {
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
export function TrendEvidenceDialog({ item, criteria, onClose }: { item?: TrendLeader; criteria: string; onClose: () => void }) {
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
