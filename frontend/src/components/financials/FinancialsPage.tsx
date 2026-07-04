import { useState } from "react"
import { useFinancials } from "@/hooks/useFinancials"
import SegmentTabs from "@/components/shared/SegmentTabs"
import PeriodToggle from "@/components/shared/PeriodToggle"
import YearToggle from "@/components/shared/YearToggle"
import ChartCard from "@/components/shared/ChartCard"
import DataTable from "@/components/shared/DataTable"
import { Button } from "@/components/ui/button"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { PercentLabel, EokLabel } from "@/components/common/ChartLabels"
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, LabelList,
} from "recharts"

interface Props {
  stockCode: string
  corpCode: string
}

const SJ_TABS = [
  { value: "IS", label: "손익계산서" },
  { value: "BS", label: "재무상태표" },
  { value: "CF", label: "현금흐름표" },
]

const CHART_ACCOUNTS: Record<string, string[]> = {
  IS: ["매출액", "영업이익", "당기순이익"],
  BS: ["자산총계", "부채총계", "자본총계"],
  CF: ["영업활동", "투자활동", "재무활동"],
}

export default function FinancialsPage({ stockCode }: Props) {
  const [sjDiv, setSjDiv] = useState("IS")
  const [period, setPeriod] = useState("annual")
  const [years, setYears] = useState(5)
  const [fsDiv, setFsDiv] = useState("CFS")
  const [viewMode, setViewMode] = useState<"table" | "chart">("table")

  const { data, isLoading } = useFinancials(stockCode, sjDiv, period, years, fsDiv)

  const chartAccounts = CHART_ACCOUNTS[sjDiv] || []
  const periods = data?.periods || []

  // Chart data in 억
  const chartData = periods.map((p, i) => {
    const point: Record<string, string | number | null> = { period: p }
    for (const row of data?.rows || []) {
      if (chartAccounts.some((a) => row.account_nm.includes(a))) {
        const val = row.values[i]
        point[row.account_nm] = val ? Math.round(parseFloat(val) / 1e8) : null
      }
    }
    // OPM + stacked segments for IS
    if (sjDiv === "IS") {
      const revRow = data?.rows.find((r) => r.account_nm.includes("매출액"))
      const opRow = data?.rows.find((r) => r.account_nm.includes("영업이익"))
      const niRow = data?.rows.find((r) => r.account_nm.includes("당기순이익"))
      const revRaw = revRow?.values[i]
      const opRaw = opRow?.values[i]
      const niRaw = niRow?.values[i]
      const rev = revRaw ? Math.round(parseFloat(revRaw) / 1e8) : 0
      const op = opRaw ? Math.round(parseFloat(opRaw) / 1e8) : 0
      const ni = niRaw ? Math.round(parseFloat(niRaw) / 1e8) : 0

      if (revRaw && opRaw) {
        const margin = (parseFloat(opRaw) / parseFloat(revRaw)) * 100
        point["OPM(%)"] = Math.round(margin * 10) / 10
      }

      // Stacked segments: 당기순이익 (bottom) → 영업이익 초과분 → 매출액 초과분 (top)
      // Handle negatives: clamp segments to 0 when relationship breaks
      if (rev > 0) {
        point["_ni"] = Math.max(ni, 0)
        point["_opExtra"] = Math.max(op - Math.max(ni, 0), 0)
        point["_revExtra"] = Math.max(rev - Math.max(op, 0), 0)
      } else {
        // Negative revenue: show as single bar
        point["_ni"] = 0
        point["_opExtra"] = 0
        point["_revExtra"] = rev
      }
      // Store original values for labels/tooltip
      point["_rev"] = rev
      point["_op"] = op
      point["_niOrig"] = ni
    }
    return point
  })

  const COLORS = ["var(--color-chart-blue)", "var(--color-chart-orange)", "var(--color-chart-green)"]

  // Custom tooltip for IS stacked bars
  const ISTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    const d = payload[0]?.payload
    if (!d) return null
    return (
      <div className="rounded-lg border bg-background px-3 py-2 text-xs shadow-md">
        <p className="font-medium mb-1">{label}</p>
        <p style={{ color: "var(--color-chart-blue)" }}>매출액: {(d._rev ?? 0).toLocaleString()}억</p>
        <p style={{ color: "var(--color-chart-orange)" }}>영업이익: {(d._op ?? 0).toLocaleString()}억</p>
        <p style={{ color: "var(--color-chart-green)" }}>당기순이익: {(d._niOrig ?? 0).toLocaleString()}억</p>
        {d["OPM(%)"] != null && <p style={{ color: "var(--color-chart-gray, #6b7280)" }}>OPM: {d["OPM(%)"]}%</p>}
      </div>
    )
  }

  // Label that shows the original 매출액 value at the top of the stacked bar
  const RevenueTotalLabel = ({ x = 0, y = 0, width = 0, index = 0 }: any) => {
    const d = chartData[index]
    if (!d || !d._rev) return null
    const rev = d._rev as number
    return (
      <text x={x + width / 2} y={y - 5} textAnchor="middle" fontSize={9} fontWeight={500} fill="#374151">
        {rev.toLocaleString("ko-KR")}
      </text>
    )
  }

  return (
    <div className="space-y-5">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <SegmentTabs tabs={SJ_TABS} value={sjDiv} onChange={setSjDiv} />
        <PeriodToggle value={period} onChange={setPeriod} />
        <YearToggle value={years} onChange={setYears} />
        <Select value={fsDiv} onValueChange={setFsDiv}>
          <SelectTrigger className="w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="CFS">주재무제표</SelectItem>
            <SelectItem value="OFS">별도재무제표</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-auto flex gap-1">
          <Button variant={viewMode === "chart" ? "outline" : "ghost"} size="sm"
            onClick={() => setViewMode("chart")}
            className={viewMode === "chart" ? "border-primary text-primary" : "text-muted-foreground"}>
            차트
          </Button>
          <Button variant={viewMode === "table" ? "outline" : "ghost"} size="sm"
            onClick={() => setViewMode("table")}
            className={viewMode === "table" ? "border-primary text-primary" : "text-muted-foreground"}>
            테이블
          </Button>
        </div>
      </div>

      {isLoading && <p className="text-muted-foreground">로딩 중...</p>}

      {data && periods.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-center py-10">데이터가 없습니다.</p>
      )}

      {data && periods.length > 0 && viewMode === "table" && (
        <DataTable periods={periods} rows={data.rows} exportFilename={`${stockCode}_${sjDiv}_${period}`} />
      )}

      {data && periods.length > 0 && viewMode === "chart" && (
        <ChartCard title={SJ_TABS.find((t) => t.value === sjDiv)?.label || ""}>
          <ResponsiveContainer width="100%" height={400}>
            <ComposedChart data={chartData} margin={{ top: 25, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v.toLocaleString()}`} axisLine={false} tickLine={false} />
              {sjDiv === "IS" && (
                <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} axisLine={false} tickLine={false} />
              )}
              {sjDiv === "IS" ? (
                <>
                  <Tooltip content={<ISTooltip />} />
                  <Legend iconType="rect" wrapperStyle={{ fontSize: 12 }}
                    payload={[
                      { value: "매출액", type: "rect", color: "var(--color-chart-blue)" },
                      { value: "영업이익", type: "rect", color: "var(--color-chart-orange)" },
                      { value: "당기순이익", type: "rect", color: "var(--color-chart-green)" },
                    ]} />
                  {/* Stack order: bottom → top = 당기순이익 → 영업이익 초과분 → 매출액 초과분 */}
                  <Bar yAxisId="left" dataKey="_ni" stackId="is" name="당기순이익"
                    fill="var(--color-chart-green)" barSize={32} />
                  <Bar yAxisId="left" dataKey="_opExtra" stackId="is" name="영업이익"
                    fill="var(--color-chart-orange)" opacity={0.7} barSize={32} />
                  <Bar yAxisId="left" dataKey="_revExtra" stackId="is" name="매출액"
                    fill="var(--color-chart-blue)" opacity={0.35} radius={[2, 2, 0, 0]} barSize={32}>
                    <LabelList content={<RevenueTotalLabel />} />
                  </Bar>
                </>
              ) : (
                <>
                  <Tooltip formatter={(v: number, name: string) => name === "OPM(%)" ? `${v}%` : `${v.toLocaleString()}억`} />
                  <Legend iconType="rect" wrapperStyle={{ fontSize: 12 }} />
                  {(data?.rows || [])
                    .filter((r) => chartAccounts.some((a) => r.account_nm.includes(a)))
                    .map((r, idx) => (
                      <Bar key={r.account_nm} yAxisId="left" dataKey={r.account_nm}
                        fill={COLORS[idx % COLORS.length]} radius={[2, 2, 0, 0]} barSize={24}>
                        <LabelList dataKey={r.account_nm} content={<EokLabel />} />
                      </Bar>
                    ))}
                </>
              )}
              {sjDiv === "IS" && (
                <Line yAxisId="right" type="monotone" dataKey="OPM(%)" stroke="var(--color-chart-gray)" strokeWidth={2.5}
                  dot={{ r: 3, fill: "var(--color-chart-gray)", stroke: "#fff", strokeWidth: 2 }}>
                  <LabelList dataKey="OPM(%)" content={<PercentLabel />} />
                </Line>
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>
      )}
    </div>
  )
}

