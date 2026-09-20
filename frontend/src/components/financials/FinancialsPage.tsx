import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import NextQuestions from "@/components/shared/NextQuestions"
import { useFinancials } from "@/hooks/useFinancials"
import SegmentTabs from "@/components/shared/SegmentTabs"
import PeriodToggle from "@/components/shared/PeriodToggle"
import YearToggle from "@/components/shared/YearToggle"
import ChartCard from "@/components/shared/ChartCard"
import DataTable from "@/components/shared/DataTable"
import { PageContainer } from "@/components/shared/PageContainer"
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
  const [params] = useSearchParams()
  const [sjDiv, setSjDiv] = useState("IS")
  const [period, setPeriod] = useState("annual")
  const [years, setYears] = useState(5)
  const [fsDiv, setFsDiv] = useState("CFS")
  const [viewMode, setViewMode] = useState<"table" | "chart">("table")

  const { data, isLoading } = useFinancials(stockCode, sjDiv, period, years, fsDiv, { storedOnly: params.has('discovery') })

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
    if (sjDiv === "IS") {
      const rev = Number(data?.rows.find(r => r.account_nm === "매출액")?.values[i])
      const rawOp = data?.rows.find(r => r.account_nm === "영업이익")?.values[i]
      point["OPM(%)"] = rev > 0 && rawOp != null ? Number(rawOp) / rev * 100 : null
    }
    return point
  })

  const COLORS = ["var(--color-chart-blue)", "var(--color-chart-orange)", "var(--color-chart-green)"]

  return (
    <PageContainer>

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
        <SegmentTabs
          className="ml-auto"
          tabs={[
            { value: "chart", label: "차트" },
            { value: "table", label: "테이블" },
          ]}
          value={viewMode}
          onChange={(v) => setViewMode(v as "table" | "chart")}
        />
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
              <Tooltip formatter={(v, name) => String(name) === "OPM(%)" ? `${Number(v).toFixed(1)}%` : `${Number(v).toLocaleString()}억`} />
              <Legend iconType="rect" wrapperStyle={{ fontSize: 12 }} />
              {(data?.rows || []).filter(r => chartAccounts.some(a => r.account_nm.includes(a))).map((r, idx) => (
                <Bar key={r.account_nm} yAxisId="left" dataKey={r.account_nm}
                  fill={COLORS[idx % COLORS.length]} barSize={24}>
                  <LabelList dataKey={r.account_nm} content={<EokLabel />} />
                </Bar>
              ))}
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
      {/* 다음 질문 — dead-end 제거 (P2-3) */}
      <NextQuestions stockCode={stockCode} context="financials" />
    </PageContainer>
  )
}
