import { useState } from "react"
import { useFinancials } from "@/hooks/useFinancials"
import { useStockPrices } from "@/hooks/useStockPrices"
import PeriodToggle from "@/components/shared/PeriodToggle"
import YearToggle from "@/components/shared/YearToggle"
import ChartCard from "@/components/shared/ChartCard"
import { PercentLabel, SparsePercentLabel, SparseEokLabel, EokLabel } from "@/components/common/ChartLabels"
import { formatPercent, formatKrw } from "@/utils/format"
import { buildRevenueOpChart, buildMarginChart, buildGrowthChart, buildRevenueNetChart, buildBSChart, buildCFChart } from "@/utils/metrics"
import AreaSeriesChart from "@/components/charts/AreaSeriesChart"
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, LabelList,
} from "recharts"

interface Props {
  stockCode: string
  corpCode: string
}

export default function MetricsPage({ stockCode }: Props) {
  const [period, setPeriod] = useState("annual")
  const [years, setYears] = useState(10)

  const { data: isData, isLoading } = useFinancials(stockCode, "IS", period, years)
  const { data: bsData } = useFinancials(stockCode, "BS", period, years)
  const { data: cfData } = useFinancials(stockCode, "CF", period, years)

  const now = new Date()
  const from = new Date(now.getFullYear() - years, now.getMonth(), now.getDate())
  const { data: priceData } = useStockPrices(stockCode, from.toISOString().slice(0, 10).replace(/-/g, ""), now.toISOString().slice(0, 10).replace(/-/g, ""))

  const periods = isData?.periods || []
  const priceItems = priceData?.items || []
  const latestMcap = priceItems[priceItems.length - 1]?.market_cap

  const revOpData = isData ? buildRevenueOpChart(isData) : []
  const marginData = isData ? buildMarginChart(isData) : []
  const growthData = isData ? buildGrowthChart(isData) : []
  const revNetData = isData ? buildRevenueNetChart(isData) : []
  const bsCompData = bsData ? buildBSChart(bsData) : []
  const cfChartData = cfData ? buildCFChart(cfData) : []


  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <PeriodToggle value={period} onChange={setPeriod} options={[{ value: "quarterly", label: "분기" }, { value: "annual", label: "연도" }]} />
        <YearToggle value={years} onChange={setYears} />
        {latestMcap && <span className="ml-auto text-sm font-semibold">현시총 {formatKrw(latestMcap)}</span>}
      </div>

      {isLoading && <p className="text-muted-foreground">로딩 중...</p>}

      {!isLoading && periods.length > 0 && (
        <>
          <div className="grid grid-cols-3 gap-5">
            <MetricChart title="매출액 & 영업이익 & OPM" data={revOpData} bars={["매출액", "영업이익"]} line="OPM(%)" isQuarterly={period === "quarterly"} />

            <ChartCard title="이익률 추이">
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={marginData} margin={{ top: 20, right: 10, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} />
                  <Tooltip formatter={(v: number) => `${v}%`} />
                  <Legend iconType="line" wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="매출총이익률" stroke="var(--color-chart-yellow)" strokeWidth={2} dot={{ r: 3 }}>
                    <LabelList content={<PercentLabel />} />
                  </Line>
                  <Line type="monotone" dataKey="영업이익률" stroke="var(--color-chart-orange)" strokeWidth={2} dot={{ r: 3 }}>
                    <LabelList content={<PercentLabel />} />
                  </Line>
                  <Line type="monotone" dataKey="순이익률" stroke="var(--color-chart-green)" strokeWidth={2} dot={{ r: 3 }}>
                    <LabelList content={<PercentLabel />} />
                  </Line>
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="성장률 (YoY)">
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={growthData} margin={{ top: 20, right: 10, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} />
                  <Tooltip formatter={(v: number) => formatPercent(v)} />
                  <Legend iconType="rect" wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="매출액성장률" fill="var(--color-chart-blue)" opacity={0.8} barSize={18} />
                  <Bar dataKey="영업이익성장률" fill="var(--color-chart-orange)" opacity={0.8} barSize={18} />
                  <Line type="monotone" dataKey="순이익성장률" stroke="var(--color-chart-green)" strokeWidth={2} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <MetricChart title="매출액 & 순이익 & 순이익률" data={revNetData} bars={["매출액", "당기순이익"]} barColors={["var(--color-chart-blue)", "var(--color-chart-green)"]} line="순이익률(%)" isQuarterly={period === "quarterly"} />

            {bsCompData.length > 0 && (
              <ChartCard title="재무현황 (자본 & 부채)">
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={bsCompData} margin={{ top: 25, right: 10, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                    <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v.toLocaleString()}`} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} />
                    <Tooltip formatter={(v: number, n: string) => n.includes("%") ? `${v}%` : `${v.toLocaleString()}억`} />
                    <Legend iconType="rect" wrapperStyle={{ fontSize: 11 }} />
                    <Bar yAxisId="left" dataKey="자본총계" stackId="bs" fill="var(--color-chart-blue)" barSize={24} />
                    <Bar yAxisId="left" dataKey="부채총계" stackId="bs" fill="var(--color-chart-orange)" barSize={24} />
                    <Line yAxisId="right" type="monotone" dataKey="부채비율(%)" stroke="var(--color-chart-gray)" strokeWidth={2} dot={{ r: 3 }}>
                      <LabelList content={<PercentLabel />} />
                    </Line>
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartCard>
            )}

            {cfChartData.length > 0 && (
              <ChartCard title="현금흐름">
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={cfChartData} margin={{ top: 20, right: 10, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v.toLocaleString()}`} />
                    <Tooltip formatter={(v: number) => `${v.toLocaleString()}억`} />
                    <Legend iconType="rect" wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="영업활동" fill="var(--color-chart-green)" barSize={18} />
                    <Bar dataKey="투자활동" fill="var(--color-chart-blue)" barSize={18} />
                    <Bar dataKey="재무활동" fill="var(--color-chart-orange)" barSize={18} />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartCard>
            )}
          </div>

          {priceItems.length > 0 && (
            <div className="grid grid-cols-2 gap-5">
              <ChartCard title="시가총액 추이">
                <AreaSeriesChart
                  data={priceItems.filter(d => d.market_cap != null).map(d => ({ time: d.trade_date, value: d.market_cap! }))}
                  height={280}
                  color="#4472C4"
                  formatValue={(v) => formatKrw(v)}
                />
              </ChartCard>
              <ChartCard title="주가 추이">
                <AreaSeriesChart
                  data={priceItems.filter(d => d.close != null).map(d => ({ time: d.trade_date, value: d.close! }))}
                  height={280}
                  color="#70AD47"
                  formatValue={(v) => v.toLocaleString() + "원"}
                />
              </ChartCard>
            </div>
          )}
        </>
      )}

      {!isLoading && periods.length === 0 && <p className="text-muted-foreground text-center py-10">데이터가 없습니다.</p>}
    </div>
  )
}

function MetricChart({ title, data, bars, barColors, line, isQuarterly }: {
  title: string; data: Record<string, unknown>[]; bars: string[]; barColors?: string[]; line: string; isQuarterly?: boolean
}) {
  const colors = barColors || ["var(--color-chart-blue)", "var(--color-chart-orange)"]
  const PctLabel = isQuarterly ? SparsePercentLabel : PercentLabel
  const BarLbl = isQuarterly ? SparseEokLabel : EokLabel
  return (
    <ChartCard title={title}>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 25, right: 10, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 11 }} />
          <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v.toLocaleString()}`} />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip formatter={(v: number, n: string) => n.includes("%") ? `${v}%` : `${v.toLocaleString()}억`} />
          <Legend iconType="rect" wrapperStyle={{ fontSize: 11 }} />
          {bars.map((b, i) => (
            <Bar key={b} yAxisId="left" dataKey={b} fill={colors[i]} radius={[2, 2, 0, 0]} barSize={isQuarterly ? 8 : 20}>
              <LabelList dataKey={b} content={<BarLbl />} />
            </Bar>
          ))}
          <Line yAxisId="right" type="monotone" dataKey={line} stroke="var(--color-chart-gray)" strokeWidth={2.5}
            dot={isQuarterly ? false : { r: 3, fill: "#A5A5A5", stroke: "#fff", strokeWidth: 2 }}>
            <LabelList dataKey={line} content={<PctLabel />} />
          </Line>
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

