import { useState, useMemo } from "react"
import { useStockPrices } from "@/hooks/useStockPrices"
import ChartCard from "@/components/shared/ChartCard"
import FilterChips from "@/components/shared/FilterChips"
import { formatKrw } from "@/utils/format"
import CandlestickChart from "@/components/charts/CandlestickChart"
import AreaSeriesChart from "@/components/charts/AreaSeriesChart"

interface Props {
  stockCode: string
}

const RANGE_OPTIONS = [
  { value: "1", label: "1년" },
  { value: "3", label: "3년" },
  { value: "5", label: "5년" },
  { value: "10", label: "10년" },
]

export default function MarketCapChart({ stockCode }: Props) {
  const [rangeYears, setRangeYears] = useState("5")
  const y = parseInt(rangeYears)
  const now = new Date()
  const from = new Date(now.getFullYear() - y, now.getMonth(), now.getDate())
  const fromDate = from.toISOString().slice(0, 10).replace(/-/g, "")
  const toDate = now.toISOString().slice(0, 10).replace(/-/g, "")

  const { data, isLoading } = useStockPrices(stockCode, fromDate, toDate)

  const items = data?.items || []

  const candleData = useMemo(
    () =>
      items
        .filter((it) => it.open != null && it.high != null && it.low != null && it.close != null)
        .map((it) => ({
          time: it.trade_date,
          open: it.open!,
          high: it.high!,
          low: it.low!,
          close: it.close!,
        })),
    [items],
  )

  const volumeData = useMemo(
    () =>
      items
        .filter((it) => it.volume != null && it.close != null && it.open != null)
        .map((it) => ({
          time: it.trade_date,
          value: it.volume!,
          color: it.close! >= it.open! ? "#ef444480" : "#3b82f680",
        })),
    [items],
  )

  const marketCapData = useMemo(
    () =>
      items
        .filter((it) => it.market_cap != null)
        .map((it) => ({ time: it.trade_date, value: it.market_cap! })),
    [items],
  )

  const formatWon = useMemo(() => (v: number) => v.toLocaleString("ko-KR"), [])

  return (
    <div className="space-y-5">
      <FilterChips options={RANGE_OPTIONS} value={rangeYears} onChange={setRangeYears} />

      {isLoading && <p className="text-muted-foreground">로딩 중...</p>}

      {candleData.length > 0 && (
        <ChartCard title="주가 추이 (OHLCV)">
          <CandlestickChart
            data={candleData}
            volumeData={volumeData}
            height={400}
            formatValue={formatWon}
          />
        </ChartCard>
      )}

      {marketCapData.length > 0 && (
        <ChartCard title="시가총액 추이">
          <AreaSeriesChart
            data={marketCapData}
            height={300}
            color="#2563eb"
            formatValue={formatKrw}
          />
        </ChartCard>
      )}
    </div>
  )
}
