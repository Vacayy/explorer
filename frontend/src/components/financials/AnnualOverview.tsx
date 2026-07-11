import { useFinancials } from "@/hooks/useFinancials"
import { useConsensus } from "@/hooks/useConsensus"
import DataTable from "@/components/shared/DataTable"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { formatKrw } from "@/utils/format"
import { buildRevenueOpChart } from "@/utils/metrics"
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, LabelList,
} from "recharts"

/**
 * 연간 개요 — 손익 차트 + 연도별 실적표(컨센서스).
 * 종목 홈에서 재무정보 탭으로 이관 (P2-1 후속: 재무·실적은 매일 보는 게 아니다).
 */
export default function AnnualOverview({ stockCode }: { stockCode: string }) {
  const { data: isData, isLoading: finLoading } = useFinancials(stockCode, "IS", "quarterly", 4)
  const { data: annualData } = useFinancials(stockCode, "IS", "annual", 5)
  const { data: consensusData } = useConsensus(stockCode)

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
  const hasTableConsensus = !!firstEst && (
    firstEst.revenue_est != null || firstEst.op_profit_est != null || firstEst.net_income_est != null
  )
  const hasEpsConsensus = !!firstEst && !hasTableConsensus && (
    firstEst.eps_est != null || firstEst.per_est != null
  )
  const hasConsensus = hasTableConsensus

  const summaryRows = annualKm
    ? (["매출액", "영업이익", "당기순이익"] as const)
        .map((k) => {
          const m = annualKm[k]
          if (!m) return null
          const estVal =
            k === "매출액" ? firstEst?.revenue_est :
            k === "영업이익" ? firstEst?.op_profit_est :
            k === "당기순이익" ? firstEst?.net_income_est : null
          const values = [...m.values, ...(hasConsensus ? [estVal != null ? String(estVal * 1e8) : null] : [])]
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
  const recentQ = qPeriods

  return (
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
                  formatter={(v, name) => String(name) === "OPM(%)" ? `${Number(v).toFixed(1)}%` : `${Number(v).toLocaleString()}억`}
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
