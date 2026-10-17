import { useSearchParams } from "react-router-dom"
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { useTwRevenue } from "@/hooks/useTwRevenue"
import { cn } from "@/lib/utils"
import { formatPercent, formatTwdEok } from "@/utils/format"
import type { TwRevenueItem } from "@/types"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/**
 * 대만 월매출 위젯 (docs/specs/tw-revenue.md) — 91개사를 밸류체인 층별로. 층은 URL tw_layer, 회사 상세는 URL tw=<코드>.
 * 행: 이름·역할 · 최근 24개월 막대 · 최신 월매출(억 TWD) · YoY · 3개월 YoY. 3개월 YoY 높은 순.
 */

const tone = (v: number | null | undefined) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up" : "text-down"

function useTwMeta(): WidgetMeta {
  const q = useTwRevenue()
  const d = q.data
  // 기준 = 가장 최근 공시 월. 매달 10일이 지나도 전전월이면 수집이 멈춘 것
  const stale = !!d?.as_of && (() => {
    const now = new Date(), [y, m] = d.as_of!.split("-").map(Number)
    const lagMonths = (now.getFullYear() - y) * 12 + (now.getMonth() + 1 - m)
    return lagMonths > 2 || (lagMonths === 2 && now.getDate() > 11)
  })()
  return { asOf: d?.as_of ? `${d.as_of} 공시` : null, stale }
}

function Bars({ series }: { series: TwRevenueItem["series"] }) {
  const s = series.slice(-24)
  const max = Math.max(...s.map(p => p.revenue ?? 0), 1)
  return <span className="flex h-5 items-end gap-px" aria-hidden>
    {s.map(p => <span key={p.ym} className="w-[3px] rounded-[1px] bg-chart-blue/70" style={{ height: `${Math.max(4, ((p.revenue ?? 0) / max) * 100)}%` }} />)}
  </span>
}

function TwRevenueBody({ w, h }: WidgetBodyProps) {
  const q = useTwRevenue()
  const [params, setParams] = useSearchParams()
  const set = (key: string, value: string | null) => setParams(prev => {
    const next = new URLSearchParams(prev)
    if (value == null) next.delete(key); else next.set(key, value)
    return next
  }, { replace: key === "tw_layer", preventScrollReset: true })
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.as_of) return <WidgetState empty emptyText="대만 월매출을 아직 받지 못했어요. 매일 11:00에 수집합니다." />
  const layer = d.layers.some(l => l.key === params.get("tw_layer")) ? params.get("tw_layer")! : d.layers[0].key
  const rows = d.items.filter(i => i.layer === layer).sort((a, b) => (b.yoy_3m ?? -1e9) - (a.yoy_3m ?? -1e9))
  const picked = d.items.find(i => i.code === params.get("tw"))
  const wide = w >= 6
  const cols = wide ? "grid-cols-[minmax(0,1fr)_92px_60px_52px_52px]" : "grid-cols-[minmax(0,1fr)_56px_52px]"
  return <div className="flex h-full flex-col gap-2">
    <div className="flex items-center gap-2">
      <Select value={layer} onValueChange={v => set("tw_layer", v)}>
        <SelectTrigger className="h-7 w-40 text-xs" aria-label="밸류체인 층"><SelectValue /></SelectTrigger>
        <SelectContent>{d.layers.map(l => <SelectItem key={l.key} value={l.key} className="text-xs">
          {l.label} · {d.items.filter(i => i.layer === l.key).length}
        </SelectItem>)}</SelectContent>
      </Select>
      <span className="ml-auto text-[11px] text-muted-foreground" title="매달 1~10일에 회사마다 전월 매출을 공시한다">
        {d.as_of} 공시 {d.reported}/{d.total}사
      </span>
    </div>
    <div className={cn("grid items-center gap-x-3 border-b px-1 pb-1 text-[11px] text-muted-foreground", cols)}>
      <span>회사</span>{wide && <span>24개월</span>}<span className="text-right">억 TWD</span>
      <span className="text-right">YoY</span>{wide && <span className="text-right" title="최근 3개월 합의 전년 대비">3M YoY</span>}
    </div>
    <ul className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2 text-[13px]">
      {rows.slice(0, h <= 3 ? 4 : rows.length).map(t => (
        <li key={t.code}>
          <Button variant="ghost" onClick={() => set("tw", t.code)} aria-label={`${t.name} 월매출 보기`}
            className={cn("grid h-auto w-full items-center gap-x-3 rounded-sm px-1 py-1 text-left text-[13px] font-normal", cols)}>
            <span className="flex min-w-0 items-baseline gap-1.5">
              <span className="truncate font-medium">{t.name}</span>
              {wide && <span className="truncate text-[11px] text-muted-foreground">{t.role}</span>}
              {t.lagging && <Badge variant="outline" className="shrink-0 px-1 text-[10px] text-muted-foreground">{t.ym?.slice(5)}월분</Badge>}
            </span>
            {wide && <Bars series={t.series} />}
            <span className="text-right tabular-nums">{formatTwdEok(t.revenue)}</span>
            <span className={cn("text-right tabular-nums", tone(t.yoy_pct))}>{formatPercent(t.yoy_pct)}</span>
            {wide && <span className={cn("text-right tabular-nums", tone(t.yoy_3m))}>{formatPercent(t.yoy_3m)}</span>}
          </Button>
        </li>
      ))}
    </ul>
    <TwRevenueDialog item={picked} onClose={() => set("tw", null)} />
  </div>
}

/** 회사 상세 — 월매출 막대 + YoY 선(이미지와 같은 읽기), 회사가 단 증감 사유 */
function TwRevenueDialog({ item, onClose }: { item?: TwRevenueItem; onClose: () => void }) {
  const data = (item?.series ?? []).map(p => ({ ym: p.ym, eok: p.revenue == null ? null : p.revenue / 100_000, yoy: p.yoy_pct }))
  return <Dialog open={!!item} onOpenChange={v => !v && onClose()}>
    <DialogContent className="sm:max-w-2xl">
      {item && <>
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-baseline gap-2">
            {item.name}<span className="text-sm font-normal text-muted-foreground">{item.code} · {item.market === "TPEx" ? "장외" : "상장"} · {item.role}</span>
          </DialogTitle>
          <DialogDescription>
            {item.ym} 월매출 {formatTwdEok(item.revenue)} TWD · YoY {formatPercent(item.yoy_pct)} · MoM {formatPercent(item.mom_pct)} · 3개월 YoY {formatPercent(item.yoy_3m)}
          </DialogDescription>
        </DialogHeader>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
            <XAxis dataKey="ym" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(2).replace("-", ".")} interval={5} />
            <YAxis yAxisId="rev" tick={{ fontSize: 10 }} width={48} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${Math.round(v).toLocaleString("ko-KR")}억`} />
            <YAxis yAxisId="yoy" orientation="right" tick={{ fontSize: 10 }} width={44} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip formatter={(v, name) => name === "YoY" ? formatPercent(Number(v)) : `${formatTwdEok(Number(v) * 100_000)} TWD`} />
            <Bar yAxisId="rev" dataKey="eok" name="월매출" fill="var(--color-chart-blue)" radius={[2, 2, 0, 0]} />
            <Line yAxisId="yoy" dataKey="yoy" name="YoY" stroke="var(--color-chart-orange)" strokeWidth={2} dot={false} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
        {item.note && <p className="text-caption text-muted-foreground">회사가 밝힌 증감 사유({item.ym}): {item.note}</p>}
        <p className="text-caption text-muted-foreground">원천: 대만 거래소 월매출 공시(MOPS·TWSE/TPEx Open API), 연결 기준 · 단위 억 TWD</p>
      </>}
    </DialogContent>
  </Dialog>
}

export const TW_WIDGETS: WidgetDef[] = [
  { id: "explore.twRevenue", title: "대만 월매출", description: "대만 반도체·IT 하드웨어·해운 91개사 월매출 · YoY · 3개월 YoY (밸류체인 층별)", section: "explore", group: "대만",
    size: { w: 6, h: 5, minW: 3, minH: 2 }, useMeta: useTwMeta, Body: TwRevenueBody },
]
