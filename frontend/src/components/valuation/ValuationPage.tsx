import { useState, useMemo } from "react"
import { useValuation } from "@/hooks/useStockPrices"
import ChartCard from "@/components/shared/ChartCard"
import FilterChips from "@/components/shared/FilterChips"
import MultiLineChart from "@/components/charts/MultiLineChart"
import type { LineConfig } from "@/components/charts/MultiLineChart"
import {
  ComposedChart, Bar, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts"

interface Props {
  stockCode: string
}

const RANGE_OPTIONS = [
  { value: "3", label: "3년" },
  { value: "5", label: "5년" },
  { value: "10", label: "10년" },
]

const PBR_LINES: LineConfig[] = [
  { key: "close", label: "수정주가", color: "#374151", lineWidth: 2 },
  { key: "pbr_p90", label: "90%", color: "#ef4444", lineStyle: 2 },
  { key: "pbr_p75", label: "75%", color: "#eab308", lineStyle: 2 },
  { key: "pbr_p50", label: "50%", color: "#22c55e", lineStyle: 2 },
  { key: "pbr_p25", label: "25%", color: "#3b82f6", lineStyle: 2 },
  { key: "pbr_p10", label: "10%", color: "#a855f7", lineStyle: 2 },
]

const PER_LINES: LineConfig[] = [
  { key: "per", label: "PER", color: "#eab308", lineWidth: 2 },
  { key: "close", label: "수정주가", color: "#9ca3af", lineStyle: 2 },
]

const formatWon = (v: number) => v.toLocaleString("ko-KR")

export default function ValuationPage({ stockCode }: Props) {
  const [rangeYears, setRangeYears] = useState("5")
  const y = parseInt(rangeYears)
  const now = new Date()
  const from = new Date(now.getFullYear() - y, now.getMonth(), now.getDate())
  const fromDate = from.toISOString().slice(0, 10).replace(/-/g, "")
  const toDate = now.toISOString().slice(0, 10).replace(/-/g, "")

  const { data, isLoading } = useValuation(stockCode, fromDate, toDate)

  const items = data?.items || []
  const pbrBands = data?.pbr_bands

  const pbrData = useMemo(() => {
    if (!pbrBands?.dates) return []
    const dates = pbrBands.dates as (string | null)[]
    return dates
      .map((d: string | null, i: number) => ({
        time: d ?? "",
        close: pbrBands.close?.[i] ?? null,
        pbr_p10: pbrBands.pbr_p10?.[i] ?? null,
        pbr_p25: pbrBands.pbr_p25?.[i] ?? null,
        pbr_p50: pbrBands.pbr_p50?.[i] ?? null,
        pbr_p75: pbrBands.pbr_p75?.[i] ?? null,
        pbr_p90: pbrBands.pbr_p90?.[i] ?? null,
      }))
      .filter((d) => d.time)
  }, [pbrBands])

  const perData = useMemo(
    () =>
      items.map((it) => ({
        time: it.trade_date,
        per: it.per,
        close: it.close,
      })),
    [items],
  )

  const epsData = useMemo(
    () =>
      items.map((it) => ({
        date: it.trade_date,
        eps: it.eps,
        close: it.close,
      })),
    [items],
  )

  return (
    <div className="space-y-5">
      <FilterChips options={RANGE_OPTIONS} value={rangeYears} onChange={setRangeYears} />

      {isLoading && <p className="text-muted-foreground">로딩 중...</p>}

      <div className="grid grid-cols-3 gap-5">
        {pbrData.length > 0 && (
          <ChartCard title="PBR 밴드 (순자산 대비)">
            <MultiLineChart
              data={pbrData}
              lines={PBR_LINES}
              height={300}
              formatValue={formatWon}
            />
          </ChartCard>
        )}

        {perData.length > 0 && (
          <ChartCard title="PER">
            <MultiLineChart
              data={perData}
              lines={PER_LINES}
              height={300}
            />
          </ChartCard>
        )}

        <ChartCard title="주당 순이익 (EPS)">
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={epsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(2, 7)} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={(v: number) => v.toLocaleString()} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v: number) => v.toLocaleString()} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="eps" name="EPS" fill="var(--color-chart-yellow)" opacity={0.7} />
              <Line yAxisId="right" type="monotone" dataKey="close" name="수정주가" stroke="var(--color-chart-gray)" dot={false} strokeDasharray="3 3" />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}
