import { useMemo } from "react"
import { useFinancials } from "@/hooks/useFinancials"
import { useStockPrices } from "@/hooks/useStockPrices"
import { useDisclosures } from "@/hooks/useDisclosures"
import { useKpi } from "@/hooks/useKpi"
import { useIRNotes } from "@/hooks/useIRNotes"
import { useConsensus } from "@/hooks/useConsensus"
import { useIndexPerformance } from "@/hooks/useIndexPerformance"
import { useWatchlist, useAddToWatchlist } from "@/hooks/useWatchlist"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import DataTable from "@/components/shared/DataTable"
import CandlestickChart from "@/components/charts/CandlestickChart"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { formatKrw, formatPercent } from "@/utils/format"
import { buildRevenueOpChart } from "@/utils/metrics"
// Chart labels defined inline at bottom of file (SparseBarLabel, SparseOpmLabel)
import {
  ComposedChart, Bar, Line, LineChart, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, LabelList,
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
  const { data: isData, isLoading: finLoading } = useFinancials(stockCode, "IS", "quarterly", 4)
  const { data: annualData } = useFinancials(stockCode, "IS", "annual", 5)
  const { data: priceData, isLoading: priceLoading } = useStockPrices(stockCode, fromDate, toDate)
  const { data: discData, isLoading: discLoading } = useDisclosures(stockCode, undefined, undefined, undefined, 1, 5)
  const { data: bullNotes, isLoading: bullLoading } = useIRNotes(stockCode, "bull")
  const { data: bearNotes, isLoading: bearLoading } = useIRNotes(stockCode, "bear")
  const { data: consensusData } = useConsensus(stockCode)
  const { data: indexPerfData, isLoading: indexLoading } = useIndexPerformance(stockCode, 365)

  // Derived data — quarterly for chart, annual for table
  // Clamp extreme OPM values (e.g. -1950%) to null to prevent Y-axis distortion
  const chartData = isData
    ? buildRevenueOpChart(isData).map((d) => ({
        ...d,
        "OPM(%)": d["OPM(%)"] != null && Math.abs(d["OPM(%)"]) <= 100 ? d["OPM(%)"] : null,
      }))
    : []

  const annualPeriods = annualData?.periods || []
  const annualKm = annualData?.key_metrics

  // Build summary rows with consensus estimate appended as rightmost column
  const firstEst = consensusData?.estimates?.[0]
  // Only show consensus column in table if at least one of revenue/op/net is available
  const hasTableConsensus = !!firstEst && (
    firstEst.revenue_est != null || firstEst.op_profit_est != null || firstEst.net_income_est != null
  )
  // Show EPS/PER info box when we have EPS data but no IS estimates
  const hasEpsConsensus = !!firstEst && !hasTableConsensus && (
    firstEst.eps_est != null || firstEst.per_est != null
  )
  const hasConsensus = hasTableConsensus

  const summaryRows = annualKm
    ? (["매출액", "영업이익", "당기순이익"] as const)
        .map((k) => {
          const m = annualKm[k]
          if (!m) return null
          // Append consensus estimate value
          const estVal =
            k === "매출액" ? firstEst?.revenue_est :
            k === "영업이익" ? firstEst?.op_profit_est :
            k === "당기순이익" ? firstEst?.net_income_est : null
          const values = [...m.values, ...(hasConsensus ? [estVal != null ? String(estVal * 1e8) : null] : [])]
          // YoY for estimate: compare to last actual
          const lastActual = m.values[m.values.length - 1]
          let estYoy: number | null = null
          if (estVal != null && lastActual) {
            const prev = parseFloat(lastActual)
            const cur = estVal * 1e8  // consensus is in 억, convert to 원
            if (prev !== 0) estYoy = Math.round((cur - prev) / Math.abs(prev) * 1000) / 10
          }
          const yoy = [...m.yoy, ...(hasConsensus ? [estYoy] : [])]
          return { account_nm: m.account_nm, values, yoy }
        })
        .filter(Boolean) as { account_nm: string; values: (string | null)[]; yoy: (number | null)[] }[]
    : []

  // Show last 4 actual years + consensus = max 5 columns (fits in card)
  const recentCount = 4
  const trimmedPeriods = annualPeriods.slice(-recentCount)
  const startIdx = annualPeriods.length - recentCount
  const trimmedRows = summaryRows.map((row) => {
    const actualValues = row.values.slice(startIdx, startIdx + recentCount)
    const actualYoy = row.yoy.slice(startIdx, startIdx + recentCount)
    // Append consensus column if available
    const estValue = hasConsensus ? row.values[row.values.length - 1] : null
    const estYoy = hasConsensus ? row.yoy[row.yoy.length - 1] : null
    return {
      ...row,
      values: hasConsensus ? [...actualValues, estValue] : actualValues,
      yoy: hasConsensus ? [...actualYoy, estYoy] : actualYoy,
    }
  })
  const displayPeriods = [
    ...trimmedPeriods,
    ...(hasConsensus && firstEst ? [firstEst.fiscal_year] : []),
  ]

  // Recent 4 quarters for mini table
  const qPeriods = isData?.periods?.slice(-4) || []
  const qKm = isData?.key_metrics
  const qRevVals = qKm?.["매출액"]?.values.slice(-4) || []
  const qOpVals = qKm?.["영업이익"]?.values.slice(-4) || []
  const qNetVals = qKm?.["당기순이익"]?.values.slice(-4) || []

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

  const recentQ = qPeriods

  // Memos (recent 3)
  const recentMemos = useMemo(() => {
    const bulls = (bullNotes || []).slice(0, 3).map(n => ({ ...n, type: "bull" as const }))
    const bears = (bearNotes || []).slice(0, 3).map(n => ({ ...n, type: "bear" as const }))
    return [...bulls, ...bears]
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, 3)
  }, [bullNotes, bearNotes])

  const memosLoading = bullLoading || bearLoading

  /* ── KPI strip values ─────────────────────────────────────── */
  const priceChangePct = kpi?.price_change_pct
  const priceChangeStr = priceChangePct != null
    ? `${priceChangePct >= 0 ? "▲" : "▼"}${formatPercent(priceChangePct)}`
    : undefined
  const priceChangeColor = priceChangePct != null
    ? priceChangePct >= 0 ? "text-red-600" : "text-blue-600"
    : undefined

  return (
    <div className="space-y-4 p-4">
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

      {/* Row 1: Candlestick (2/3) | Relative Performance (1/3) */}
      <div className="grid grid-cols-3 gap-4">
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
                    formatter={(v: number, name: string) => [`${v.toFixed(1)}`, name]}
                    labelFormatter={(l: string) => l}
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

      {/* Row 2: 실적 그래프 | 실적 테이블 */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>손익계산서</CardTitle>
          </CardHeader>
          <CardContent>
            {finLoading ? (
              <Skeleton className="h-[340px] w-full rounded" />
            ) : chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={340}>
                <ComposedChart data={chartData} margin={{ top: 20, right: 50, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f7" vertical={false} />
                  <XAxis
                    dataKey="period"
                    tick={{ fontSize: 11, fill: "#86868b" }}
                    axisLine={{ stroke: "#d2d2d7" }}
                    tickLine={false}
                  />
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 10, fill: "#86868b" }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v: number) => v.toLocaleString()}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 10, fill: "#86868b" }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v: number) => `${v}%`}
                    domain={[-100, 100]}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: 8, border: "1px solid #d2d2d7", fontSize: 12 }}
                    formatter={(v: number, name: string) => name === "OPM(%)" ? `${v.toFixed(1)}%` : `${v.toLocaleString()}억`}
                  />
                  <Legend iconType="rect" iconSize={10} wrapperStyle={{ fontSize: 11, color: "#86868b" }} />
                  {/* 3 overlay bars: 매출(wide, light) → 영업(medium) → 순이익(narrow, bright) */}
                  <Bar yAxisId="left" dataKey="매출액" fill="#0071e3" fillOpacity={0.3} radius={[2, 2, 0, 0]} barSize={chartData.length > 20 ? 14 : 24}>
                    <LabelList dataKey="매출액" content={<SparseBarLabel total={chartData.length} />} />
                  </Bar>
                  <Bar yAxisId="left" dataKey="영업이익" fill="#ff9f0a" fillOpacity={0.7} radius={[2, 2, 0, 0]} barSize={chartData.length > 20 ? 10 : 18}>
                    <LabelList dataKey="영업이익" content={<SparseBarLabel total={chartData.length} />} />
                  </Bar>
                  <Bar yAxisId="left" dataKey="당기순이익" fill="#34c759" fillOpacity={0.9} radius={[2, 2, 0, 0]} barSize={chartData.length > 20 ? 6 : 12}>
                    <LabelList dataKey="당기순이익" content={<SparseBarLabel total={chartData.length} />} />
                  </Bar>
                  {/* OPM smooth curve */}
                  <Line
                    yAxisId="right"
                    type="natural"
                    dataKey="OPM(%)"
                    stroke="#86868b"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "#fff", stroke: "#86868b", strokeWidth: 1.5 }}
                    activeDot={{ r: 5, fill: "#86868b", stroke: "#fff", strokeWidth: 2 }}
                  >
                    <LabelList dataKey="OPM(%)" content={<SparseOpmLabel total={chartData.length} />} />
                  </Line>
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-[340px] text-sm text-muted-foreground">
                실적 데이터가 없습니다
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>실적 요약 (연도별)</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[300px]">
              {finLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full rounded" />
                  <Skeleton className="h-4 w-3/4 rounded" />
                  <Skeleton className="h-4 w-5/6 rounded" />
                </div>
              ) : (
                <>
                  {summaryRows.length > 0 && (
                    <div className="mb-4">
                      <DataTable periods={displayPeriods} rows={trimmedRows} />
                      {hasEpsConsensus && firstEst && (
                        <div className="mt-2 px-2 py-1.5 rounded bg-muted/50 text-xs text-muted-foreground flex gap-3">
                          <span className="font-medium text-foreground">컨센서스 ({firstEst.fiscal_year})</span>
                          {firstEst.eps_est != null && <span>EPS {firstEst.eps_est.toLocaleString("ko-KR")}원</span>}
                          {firstEst.per_est != null && <span>PER {firstEst.per_est.toFixed(1)}배</span>}
                          {firstEst.target_price != null && <span>목표가 {firstEst.target_price.toLocaleString("ko-KR")}원</span>}
                          {firstEst.analyst_count != null && <span>{firstEst.analyst_count}개사</span>}
                        </div>
                      )}
                    </div>
                  )}

                  {recentQ.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold mb-2 text-muted-foreground">최근 분기</h3>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="bg-muted/50 border-b">
                            <th className="px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground w-[80px]">구분</th>
                            {recentQ.map((q) => (
                              <th key={q} className="px-2 py-1.5 text-right text-xs font-semibold text-muted-foreground">{q}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {[
                            { label: "매출액", vals: qRevVals },
                            { label: "영업이익", vals: qOpVals },
                            { label: "순이익", vals: qNetVals },
                          ].map((row) => (
                            <tr key={row.label} className="border-b border-border/50">
                              <td className="px-2 py-1 text-xs font-medium">{row.label}</td>
                              {row.vals.map((v, i) => (
                                <td key={i} className="px-2 py-1 text-right text-xs tabular-nums">
                                  {v ? formatKrw(parseFloat(v)) : "-"}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {summaryRows.length === 0 && recentQ.length === 0 && (
                    <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
                      실적 데이터가 없습니다
                    </div>
                  )}
                </>
              )}
            </ScrollArea>
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

        <Card>
          <CardHeader>
            <CardTitle>투자 논점</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[250px]">
              {memosLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full rounded" />
                  <Skeleton className="h-4 w-2/3 rounded" />
                </div>
              ) : recentMemos.length > 0 ? (
                <ul className="space-y-2">
                  {recentMemos.map((memo) => (
                    <li key={memo.id} className="text-xs">
                      <span className={memo.type === "bull" ? "text-red-600" : "text-blue-600"}>
                        {memo.type === "bull" ? "▲ Bull" : "▼ Bear"}
                      </span>{" "}
                      <span className="font-medium">{memo.title}</span>
                      {memo.content && (
                        <p className="text-muted-foreground mt-0.5 line-clamp-2">{memo.content}</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">메모가 없습니다</p>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/* ── Chart label helpers (Butler style: sparse labels to avoid clutter) ── */

function SparseBarLabel({ x = 0, y = 0, width = 0, index = 0, value, total = 0 }: {
  x?: number; y?: number; width?: number; index?: number; value?: number | null; total?: number
}) {
  if (!value) return null
  // Show every 4th label for quarterly data (16+ points), every label for annual (≤10)
  const interval = total > 12 ? 4 : 1
  if (index % interval !== 0 && total > 12) return null
  return (
    <text x={x + width / 2} y={y - 4} textAnchor="middle" fontSize={9} fontWeight={500} fill="#1d1d1f">
      {value.toLocaleString("ko-KR")}
    </text>
  )
}

function SparseOpmLabel({ x = 0, y = 0, index = 0, value, total = 0 }: {
  x?: number; y?: number; index?: number; value?: number | null; total?: number
}) {
  if (value == null) return null
  const interval = total > 12 ? 4 : 1
  if (index % interval !== 0 && total > 12) return null
  return (
    <text x={x} y={y - 10} textAnchor="middle" fontSize={9} fontWeight={600} fill="#86868b">
      {value.toFixed(1)}%
    </text>
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
