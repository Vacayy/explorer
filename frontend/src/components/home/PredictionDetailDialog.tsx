import { ExternalLink, Pin } from "lucide-react"
import MultiLineChart from "@/components/charts/MultiLineChart"
import { useChartTheme } from "@/components/charts/chartTheme"
import { BlockError } from "@/components/home/blockState"
import { Seg } from "@/components/home/MarketFrame"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { usePinPrediction, usePredictionDetail } from "@/hooks/usePredictions"
import { track } from "@/lib/usage"
import { cn } from "@/lib/utils"
import { useUrlParam } from "@/hooks/useUrlParam"
import { formatKstSlashDate, formatNumber, formatProbability } from "@/utils/format"
import type { KalshiDetail } from "@/types"

const RANGES = [{ key: "1m", label: "1개월" }, { key: "3m", label: "3개월" }, { key: "1y", label: "1년" }]
const STATUS_KO: Record<string, string> = { active: "거래 중", open: "거래 중", closed: "마감", settled: "확정", finalized: "확정", determined: "결정됨", initialized: "대기" }

/** 마감일 — 올해면 MM/DD, 아니면 YYYY/MM/DD */
export const closeLabel = (ts: string) => {
  const md = formatKstSlashDate(ts, false)
  return ts.slice(0, 4) === String(new Date().getFullYear()) ? md : `${ts.slice(0, 4)}/${md}`
}

/** 추적 핀 — 카드·상세 창 공용 */
export function PinButton({ eventTicker, seriesTicker, pinned, className }: { eventTicker: string; seriesTicker: string; pinned: boolean; className?: string }) {
  const pin = usePinPrediction()
  const on = pin.isPending ? !pinned : pinned
  return <Tooltip>
    <TooltipTrigger asChild>
      <Button variant="ghost" size="icon" aria-pressed={on} aria-label={on ? "추적 끄기" : "추적하기"} disabled={pin.isPending}
        className={cn("size-7", on ? "text-ink" : "text-ink-3", className)}
        onClick={() => {
          track("action", on ? "predictions.unpin" : "predictions.pin", { entity: `kalshi:${eventTicker}` })
          pin.mutate({ eventTicker, seriesTicker, pinned: !on })
        }}>
        <Pin className={cn("size-4", on && "fill-current")} />
      </Button>
    </TooltipTrigger>
    <TooltipContent>{on ? "추적 중 — 누르면 끄기" : "추적하기 — 인기순에서 빠져도 계속 받아 맨 앞에"}</TooltipContent>
  </Tooltip>
}

/** 상세 창 열림 상태 — URL `pm`(이벤트 티커) */
export function usePredictionDetailParam() {
  const [open, setOpen] = useUrlParam("pm", "")
  return { open, show: (t: string) => setOpen(t), close: () => setOpen("") }
}

/** 예측시장 상세 — 결과별 확률 추이(상위 4개) · 결과 전부 표 · 규칙 · 추적 핀. 기간 URL `pm_range`. */
export function PredictionDetailDialog() {
  const { open, close } = usePredictionDetailParam()
  const [range, setRange] = useUrlParam("pm_range", "3m")
  const q = usePredictionDetail(open, range)
  const d = q.data
  return <Dialog open={!!open} onOpenChange={v => !v && close()}>
    <DialogContent className="max-h-[88dvh] overflow-y-auto sm:max-w-3xl">
      <DialogHeader className="pr-8">
        <div className="flex flex-wrap items-center gap-2 text-[11.5px] text-ink-3">
          {d && <Badge variant="outline" className="font-normal">{d.category_label}</Badge>}
          {d?.close_ts && <span className="font-mono tabular-nums">{closeLabel(d.close_ts)} 마감</span>}
          {d && <PinButton eventTicker={d.event_ticker} seriesTicker={d.series_ticker} pinned={d.pinned} className="-my-1" />}
        </div>
        <DialogTitle className="text-lg leading-snug">{d?.title ?? (q.isPending ? "불러오는 중" : "예측시장")}</DialogTitle>
        <DialogDescription className={d?.subtitle ? "text-[13px] text-ink-2" : "sr-only"}>{d?.subtitle ?? "Kalshi 예측시장 상세"}</DialogDescription>
      </DialogHeader>
      {q.isPending ? <Skeleton className="h-[420px] w-full" />
        : q.isError ? <BlockError message="Kalshi에서 상세를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
        : d && <Body d={d} range={range} setRange={setRange} />}
    </DialogContent>
  </Dialog>
}

function Body({ d, range, setRange }: { d: KalshiDetail; range: string; setRange: (v: string) => void }) {
  const theme = useChartTheme()
  // 결과마다 다른 색·선 — 정체성은 끝 라벨·범례가 함께 진다(색만으로 구분하지 않는다)
  const styles = [{ color: theme.ink, lineStyle: 0 }, { color: theme.hyp, lineStyle: 0 }, { color: theme.ink3, lineStyle: 2 }, { color: theme.ink2, lineStyle: 1 }]
  const byDay = new Map<string, Record<string, unknown>>()
  d.series.forEach((s, i) => s.points.forEach(([day, v]) => {
    const row = byDay.get(day) ?? { time: day }
    row[`s${i}`] = v
    byDay.set(day, row)
  }))
  const data = [...byDay.values()].sort((a, b) => String(a.time).localeCompare(String(b.time)))
  return <div className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold">확률 추이</h3>
        <Seg label="기간" value={range} items={RANGES} onChange={setRange} className="ml-auto" />
      </div>
      {data.length > 1
        ? <MultiLineChart data={data} height={260} showLegend formatValue={v => formatProbability(v)}
            lines={d.series.map((s, i) => ({ key: `s${i}`, label: s.label, ...styles[i % styles.length] }))} />
        : <p className="py-8 text-center text-sm text-muted-foreground">이 기간의 체결 기록이 없어요.</p>}
    </div>

    <div className="flex flex-col gap-1.5">
      <h3 className="text-sm font-semibold">결과 {formatNumber(d.outcomes.length)}개{d.mutually_exclusive ? "" : " · 기준선별"}</h3>
      <div className="max-h-[280px] overflow-y-auto border">
        <Table>
          <TableHeader><TableRow>
            <TableHead>결과</TableHead><TableHead className="text-right">확률</TableHead>
            <TableHead className="text-right">24시간 거래</TableHead><TableHead className="text-right">누적 거래</TableHead><TableHead>상태</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {d.outcomes.map(o => <TableRow key={o.ticker ?? o.label}>
              <TableCell className="max-w-[260px] truncate" title={o.label}>{o.label}</TableCell>
              <TableCell className="text-right font-mono font-semibold tabular-nums">{formatProbability(o.price)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{formatNumber(o.volume_24h)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{formatNumber(o.volume)}</TableCell>
              <TableCell className="text-ink-3">{o.result ? `확정: ${o.result === "yes" ? "예" : o.result === "no" ? "아니오" : o.result}` : STATUS_KO[o.status] ?? o.status}</TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
      </div>
    </div>

    {d.rules && <div className="flex flex-col gap-1">
      <h3 className="text-sm font-semibold">판정 규칙</h3>
      <p className="text-[13px] leading-relaxed text-ink-2">{d.rules}</p>
    </div>}

    <a href={d.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 self-end text-xs text-ink-3 hover:text-ink hover:underline">
      Kalshi에서 보기 <ExternalLink className="size-3" aria-hidden />
    </a>
  </div>
}
