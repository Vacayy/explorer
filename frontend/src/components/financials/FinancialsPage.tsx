import { useSearchParams } from "react-router-dom"
import { QueryState } from "@/components/shared/QueryState"
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
  corpCode?: string
  publicView?: boolean
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

export default function FinancialsPage({ stockCode, publicView = false }: Props) {
  const [params, setParams] = useSearchParams()
  const choice = (key: string, allowed: string[], fallback: string) => {
    const value = params.get(key)
    return value && allowed.includes(value) ? value : fallback
  }
  const change = (key: string, value: string) => setParams(previous => {
    const next = new URLSearchParams(previous); next.set(key, value); return next
  })
  const sjDiv = choice('sj', ['IS', 'BS', 'CF'], 'IS')
  const period = choice('period', ['annual', 'quarterly', 'trailing'], 'annual')
  const years = Number(choice('years', ['5', '10'], '5'))
  const fsDiv = choice('fs', ['CFS', 'OFS'], 'CFS')
  const viewMode = choice('display', ['table', 'chart'], 'table')
  const query = useFinancials(stockCode, sjDiv, period, years, fsDiv, { storedOnly: publicView || params.has('discovery') })
  const { data } = query

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
        <SegmentTabs tabs={SJ_TABS} value={sjDiv} onChange={value => change('sj', value)} />
        <PeriodToggle value={period} onChange={value => change('period', value)} />
        <YearToggle value={years} onChange={value => change('years', String(value))} />
        <Select value={fsDiv} onValueChange={value => change('fs', value)}>
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
          onChange={value => change('display', value)}
        />
      </div>

      {publicView && <div className="space-y-1 text-sm text-muted-foreground">
        <p>출처: <a href="https://opendart.fss.or.kr/intro/main.do" target="_blank" rel="noreferrer" className="underline">OpenDART</a> · 저장된 재무 자료. 조회 시 새 자료를 수집하지 않습니다.</p>
        <p>통화와 정정 이력을 보관하지 않아 최신 정정본 여부는 확인할 수 없습니다. 표·차트의 억/조는 저장 금액의 표시 배율입니다.</p>
      </div>}
      {data && <p className="text-sm" role="status">표시 기준: {data.fs_div === 'CFS' ? '연결재무제표' : '별도재무제표'}
        {data.fs_div !== fsDiv && ' · 연결 자료가 없어 별도 자료를 표시합니다.'}
        {sjDiv === 'BS' && ' · 기간말 시점 값이며 합산하지 않습니다.'}
        {sjDiv !== 'BS' && period === 'trailing' && ' · 연속 네 분기가 모두 있는 기간만 합산합니다.'}
      </p>}
      <QueryState query={query} isEmpty={value => value.periods.length === 0} emptyMessage="선택한 조건으로 표시할 저장 재무 자료가 없습니다.">
        {value => <>
        {value.rows.some(row => row.values.some(v => v === null)) && <p role="status" className="text-sm text-muted-foreground">일부 항목이 누락되어 있습니다. 빈 값은 0으로 추정하지 않습니다.</p>}
      {data && periods.length > 0 && viewMode === "table" && (
        <DataTable periods={periods} rows={data.rows} unit={publicView ? "저장 금액 (억/조 배율)" : undefined} exportFilename={`${stockCode}_${sjDiv}_${period}`} />
      )}

      {data && periods.length > 0 && viewMode === "chart" && (
        <ChartCard title={SJ_TABS.find((t) => t.value === sjDiv)?.label || ""}>
          <ResponsiveContainer width="100%" height={400}>
            <ComposedChart data={chartData} margin={{ top: 25, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
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
        </>}
      </QueryState>
      {/* 다음 질문 — dead-end 제거 (P2-3) */}
      {!publicView && <NextQuestions stockCode={stockCode} context="financials" />}
    </PageContainer>
  )
}
