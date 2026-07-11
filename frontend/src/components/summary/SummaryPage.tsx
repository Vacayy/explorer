import { useMemo } from "react"
import { useStockPrices } from "@/hooks/useStockPrices"
import { useDisclosures } from "@/hooks/useDisclosures"
import { useKpi } from "@/hooks/useKpi"
import { useIndexPerformance } from "@/hooks/useIndexPerformance"
import { useWatchlist, useAddToWatchlist } from "@/hooks/useWatchlist"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import CandlestickChart from "@/components/charts/CandlestickChart"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { formatKrw, formatPercent } from "@/utils/format"
import StockBriefCard from "@/components/summary/StockBriefCard"
import ThesisSection from "@/components/summary/ThesisSection"
import AskedSection from "@/components/summary/AskedSection"
import DigestSection from "@/components/analyze/DigestSection"
import MentionsPanel from "@/components/summary/MentionsPanel"
import { PageContainer } from "@/components/shared/PageContainer"
import {
  Legend, Line, LineChart, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts"

interface Props {
  stockCode: string
  corpCode: string
}

/* ── tiny helpers ─────────────────────────────────────────────── */

function KpiItem({ label, value, sub, subColor }: {
  label: string
  value: string
  sub?: string
  subColor?: string
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5 text-sm">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="font-semibold">{value}</span>
      {sub && <span className={`text-xs ${subColor ?? "text-muted-foreground"}`}>{sub}</span>}
    </span>
  )
}

/* ── main component ───────────────────────────────────────────── */

export default function SummaryPage({ stockCode, corpCode }: Props) {
  const now = new Date()
  const from5y = new Date(now.getFullYear() - 5, now.getMonth(), now.getDate())
  const fromDate = from5y.toISOString().slice(0, 10).replace(/-/g, "")
  const toDate = now.toISOString().slice(0, 10).replace(/-/g, "")

  // Data fetching
  const { data: kpi, isLoading: kpiLoading } = useKpi(stockCode)
  const { data: priceData, isLoading: priceLoading } = useStockPrices(stockCode, fromDate, toDate)
  const { data: discData, isLoading: discLoading } = useDisclosures(stockCode, undefined, undefined, undefined, 1, 5)
  const { data: indexPerfData, isLoading: indexLoading } = useIndexPerformance(stockCode, 365)

  const priceItems = priceData?.items || []

  const candleData = useMemo(() =>
    priceItems
      .filter(it => it.open != null && it.high != null && it.low != null && it.close != null)
      .map(it => ({
        time: it.trade_date,
        open: it.open!,
        high: it.high!,
        low: it.low!,
        close: it.close!,
      })),
    [priceItems]
  )

  const volumeData = useMemo(() =>
    priceItems
      .filter(it => it.volume != null && it.close != null && it.open != null)
      .map(it => ({
        time: it.trade_date,
        value: it.volume!,
        color: it.close! >= it.open! ? "#ff3b3080" : "#0071e380",
      })),
    [priceItems]
  )

  /* ── KPI strip values ─────────────────────────────────────── */
  const priceChangePct = kpi?.price_change_pct
  const priceChangeStr = priceChangePct != null
    ? `${priceChangePct >= 0 ? "▲" : "▼"}${formatPercent(priceChangePct)}`
    : undefined
  const priceChangeColor = priceChangePct != null
    ? priceChangePct >= 0 ? "text-red-600" : "text-blue-600"
    : undefined

  return (
    <PageContainer gap="sm">
      {/* Row 0: KPI Strip */}
      {kpiLoading ? (
        <div className="flex items-center gap-3 px-4 py-2 border-b bg-card">
          <Skeleton className="h-5 w-20 rounded" />
          <Skeleton className="h-5 w-24 rounded" />
          <Skeleton className="h-5 w-16 rounded" />
          <Skeleton className="h-5 w-16 rounded" />
          <Skeleton className="h-5 w-20 rounded" />
          <Skeleton className="h-5 w-16 rounded" />
        </div>
      ) : kpi ? (
        <div className="flex items-center gap-3 px-4 py-2 border-b bg-card flex-wrap">
          <KpiItem
            label="현재가"
            value={kpi.close != null ? `${kpi.close.toLocaleString("ko-KR")}원` : "-"}
            sub={priceChangeStr}
            subColor={priceChangeColor}
          />
          <Separator orientation="vertical" className="h-6" />
          <KpiItem label="시가총액" value={kpi.market_cap != null ? formatKrw(kpi.market_cap) : "-"} />
          <Separator orientation="vertical" className="h-6" />
          <KpiItem
            label="PER(fwd)"
            value={kpi.fwd_per != null ? `${kpi.fwd_per.toFixed(1)}배` : kpi.per != null ? `${kpi.per.toFixed(1)}배` : "-"}
            sub={kpi.fwd_per != null ? "12m fwd" : kpi.per != null ? "trailing" : undefined}
          />
          <Separator orientation="vertical" className="h-6" />
          <KpiItem label="PBR" value={kpi.pbr != null ? `${kpi.pbr.toFixed(2)}배` : "-"} />
          <Separator orientation="vertical" className="h-6" />
          <KpiItem
            label="목표가"
            value={kpi.target_price_consensus != null ? `${kpi.target_price_consensus.toLocaleString("ko-KR")}원` : "-"}
            sub={kpi.target_price_consensus != null && kpi.close != null
              ? `${((kpi.target_price_consensus - kpi.close) / kpi.close * 100) >= 0 ? "+" : ""}${((kpi.target_price_consensus - kpi.close) / kpi.close * 100).toFixed(1)}%`
              : undefined}
            subColor={kpi.target_price_consensus != null && kpi.close != null
              ? (kpi.target_price_consensus >= kpi.close ? "text-red-600" : "text-blue-600")
              : undefined}
          />
          <Separator orientation="vertical" className="h-6" />
          <KpiItem
            label="영업이익률"
            value={kpi.op_margin != null ? `${kpi.op_margin.toFixed(1)}%` : "-"}
            sub={kpi.op_margin_change != null ? `${kpi.op_margin_change >= 0 ? "+" : ""}${kpi.op_margin_change.toFixed(1)}%p` : undefined}
          />
          <Separator orientation="vertical" className="h-6" />
          <KpiItem
            label="ROE"
            value={kpi.roe != null ? `${kpi.roe.toFixed(1)}%` : "-"}
            sub={kpi.roe_change != null ? `${kpi.roe_change >= 0 ? "+" : ""}${kpi.roe_change.toFixed(1)}%p` : undefined}
          />
          <Separator orientation="vertical" className="h-6" />
          <WatchlistButton stockCode={stockCode} corpCode={corpCode} />
        </div>
      ) : null}

      {/* 2컬럼: 좌 = 사실 데이터(차트·공시·논지) / 우 = AI 종합(브리프·1D/7D 요약) */}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_420px] gap-4 items-start">
      <div className="space-y-4 min-w-0">

      {/* Row 1: Candlestick (2/3) | Relative Performance (1/3) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="col-span-2">
          <CardContent className="p-4">
            {priceLoading ? (
              <Skeleton className="h-[300px] w-full rounded" />
            ) : candleData.length > 0 ? (
              <CandlestickChart data={candleData} volumeData={volumeData} height={300} />
            ) : (
              <div className="flex items-center justify-center h-[300px] text-sm text-muted-foreground">
                주가 데이터가 없습니다
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">상대 수익률 (1년)</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            {indexLoading ? (
              <Skeleton className="h-[260px] w-full rounded" />
            ) : indexPerfData && indexPerfData.data.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart
                  data={indexPerfData.data}
                  margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f7" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 9, fill: "#86868b" }}
                    axisLine={{ stroke: "#d2d2d7" }}
                    tickLine={false}
                    tickFormatter={(v: string) => v.slice(5)}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 9, fill: "#86868b" }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v: number) => `${v}`}
                    domain={["auto", "auto"]}
                    width={32}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: 8, border: "1px solid #d2d2d7", fontSize: 11 }}
                    formatter={(v, name) => [`${Number(v).toFixed(1)}`, String(name)]}
                    labelFormatter={(l) => l}
                  />
                  <Legend iconType="line" iconSize={12} wrapperStyle={{ fontSize: 10 }} />
                  <Line
                    type="monotone"
                    dataKey="stock"
                    name="종목"
                    stroke="#0071e3"
                    strokeWidth={1.5}
                    dot={false}
                    activeDot={{ r: 3 }}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="index"
                    name={indexPerfData.market}
                    stroke="#86868b"
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                    dot={false}
                    activeDot={{ r: 3 }}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-[260px] text-sm text-muted-foreground">
                데이터가 없습니다
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Row 3: 최근 공시 | 투자 논점 */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>최근 공시</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[250px]">
              {discLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full rounded" />
                  <Skeleton className="h-4 w-3/4 rounded" />
                  <Skeleton className="h-4 w-5/6 rounded" />
                </div>
              ) : discData && discData.items.length > 0 ? (
                <ul className="space-y-1.5">
                  {discData.items.map((item) => (
                    <li key={item.rcp_no} className="text-xs">
                      <span className="text-muted-foreground">{item.rcept_dt}</span>{" "}
                      {item.dart_url ? (
                        <a href={item.dart_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                          {item.report_nm}
                        </a>
                      ) : (
                        <span>{item.report_nm}</span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">공시 데이터가 없습니다</p>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* 내 논지 4분면 — 보관함 투자메모에서 이관 (P2-1). 항목 변경 시 브리프 재생성 대상 */}
        <ThesisSection stockCode={stockCode} />
      </div>

      {/* 내가 물어본 것들 — 이 종목 앵커 대화 (P2-0 데이터의 첫 노출) */}
      <AskedSection stockCode={stockCode} />

      </div>{/* /좌측 메인 */}

      {/* 우측: AI/언급 축 — 브리프 → 1D/7D 요약 → 신호 → 언급 문서 → 매칭 키워드 */}
      <div className="space-y-4 min-w-0">
        <StockBriefCard stockCode={stockCode} />
        <DigestSection stockCode={stockCode} stack />
        <MentionsPanel stockCode={stockCode} />
      </div>

      </div>{/* /2컬럼 */}
    </PageContainer>
  )
}

/* ── Watchlist add button for KPI strip ── */

function WatchlistButton({ stockCode, corpCode }: { stockCode: string; corpCode: string }) {
  const { data: watchlist = [] } = useWatchlist()
  const addToWatchlist = useAddToWatchlist()
  const isInWatchlist = watchlist.some((w) => w.stock_code === stockCode)

  if (isInWatchlist) {
    return (
      <span className="text-xs text-muted-foreground flex items-center gap-1">
        <span className="text-amber-500">★</span> 워치리스트
      </span>
    )
  }

  return (
    <Button
      variant="outline"
      size="xs"
      onClick={() => {
        addToWatchlist.mutate(
          { stock_code: stockCode, corp_code: corpCode, corp_name: "", conviction: 3 },
          { onSuccess: () => toast.success("워치리스트에 추가되었습니다") }
        )
      }}
      disabled={addToWatchlist.isPending}
    >
      + 워치리스트
    </Button>
  )
}
