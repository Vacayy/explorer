import { useSearchParams, Link } from "react-router-dom"
import { useCompare } from "@/hooks/useCompare"
import { useWatchlist } from "@/hooks/useWatchlist"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber, formatPercent } from "@/utils/format"
import CompanySearchCombobox from "@/components/shared/CompanySearchCombobox"
import { PageContainer } from "@/components/shared/PageContainer"
import type { Company } from "@/types"

// Metric row definitions
interface MetricRow {
  label: string
  key: string
  format: (v: number | null | undefined) => string
  higherIsBetter: boolean
}

const METRICS: MetricRow[] = [
  { label: "현재가", key: "close", format: (v) => (v != null ? `${formatNumber(v)}원` : "-"), higherIsBetter: false },
  { label: "시가총액", key: "market_cap", format: (v) => (v != null ? formatKrw(v) : "-"), higherIsBetter: false },
  { label: "PER (fwd)", key: "fwd_per", format: (v) => (v != null ? `${v.toFixed(1)}배` : "-"), higherIsBetter: false },
  { label: "PER (trailing)", key: "per", format: (v) => (v != null ? `${v.toFixed(1)}배` : "-"), higherIsBetter: false },
  { label: "PBR", key: "pbr", format: (v) => (v != null ? `${v.toFixed(2)}배` : "-"), higherIsBetter: false },
  { label: "영업이익률", key: "op_margin", format: (v) => (v != null ? `${v.toFixed(1)}%` : "-"), higherIsBetter: true },
  { label: "ROE", key: "roe", format: (v) => (v != null ? `${v.toFixed(1)}%` : "-"), higherIsBetter: true },
  { label: "매출성장률 (YoY)", key: "revenue_growth", format: (v) => (v != null ? formatPercent(v) : "-"), higherIsBetter: true },
  { label: "영익성장률 (YoY)", key: "op_profit_growth", format: (v) => (v != null ? formatPercent(v) : "-"), higherIsBetter: true },
  { label: "목표가", key: "target_price_consensus", format: (v) => (v != null ? `${formatNumber(v)}원` : "-"), higherIsBetter: false },
]

function getBestIndex(items: Record<string, unknown>[], key: string, higherIsBetter: boolean): number {
  const values = items.map((item) => item[key] as number | null)
  const valid = values.filter((v): v is number => v != null)
  if (valid.length === 0) return -1
  const best = higherIsBetter ? Math.max(...valid) : Math.min(...valid)
  return values.findIndex((v) => v === best)
}

function CompanySelector({
  selected,
  onAdd,
  onRemove,
}: {
  selected: { stock_code: string; corp_name: string }[]
  onAdd: (stock_code: string, corp_name: string) => void
  onRemove: (stock_code: string) => void
}) {
  const { data: watchlist } = useWatchlist()

  function handleSelect(company: Company) {
    if (company.stock_code && !selected.find((s) => s.stock_code === company.stock_code)) {
      onAdd(company.stock_code, company.corp_name)
    }
  }

  return (
    <div className="space-y-3">
      {/* Selected badges */}
      <div className="flex flex-wrap gap-2 min-h-8">
        {selected.map((s) => (
          <Badge key={s.stock_code} variant="secondary" className="gap-1 text-sm py-1 px-2">
            <Link to={`/analyze/${s.stock_code}/summary`} className="hover:underline">
              {s.corp_name}
            </Link>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemove(s.stock_code)}
              className="h-auto p-0 ml-1 text-muted-foreground hover:text-foreground hover:bg-transparent"
            >
              ✕
            </Button>
          </Badge>
        ))}
        {selected.length === 0 && (
          <span className="text-sm text-muted-foreground">비교할 기업을 추가하세요 (최대 5개)</span>
        )}
      </div>

      {/* Search combobox */}
      {selected.length < 5 && (
        <CompanySearchCombobox
          value={null}
          onSelect={handleSelect}
          placeholder="기업명 또는 종목코드 검색"
          className="max-w-sm"
        />
      )}

      {/* Watchlist quick-add */}
      {watchlist && watchlist.length > 0 && (
        <div className="flex flex-wrap gap-1 items-center">
          <span className="text-xs text-muted-foreground">워치리스트:</span>
          {watchlist
            .filter((w) => !selected.find((s) => s.stock_code === w.stock_code))
            .slice(0, 8)
            .map((w) => (
              <Button
                key={w.stock_code}
                variant="outline"
                size="sm"
                onClick={() => onAdd(w.stock_code, w.corp_name)}
                disabled={selected.length >= 5}
                className="h-auto font-normal text-xs px-2 py-0.5 rounded border hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
              >
                + {w.corp_name}
              </Button>
            ))}
        </div>
      )}
    </div>
  )
}

export default function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const stocksParam = searchParams.get("stocks") ?? ""
  const stockCodes = stocksParam ? stocksParam.split(",").filter(Boolean) : []

  const { data, isLoading, isError } = useCompare(stockCodes)

  // Build selected list from URL (fallback corp_name to stock_code until data loads)
  const dataMap = Object.fromEntries((data?.items ?? []).map((item) => [item.stock_code, item]))
  const selected = stockCodes.map((code) => ({
    stock_code: code,
    corp_name: dataMap[code]?.corp_name ?? code,
  }))

  function handleAdd(stock_code: string, _corp_name: string) {
    if (stockCodes.includes(stock_code) || stockCodes.length >= 5) return
    const next = [...stockCodes, stock_code].join(",")
    setSearchParams({ stocks: next })
  }

  function handleRemove(stock_code: string) {
    const next = stockCodes.filter((c) => c !== stock_code).join(",")
    if (next) {
      setSearchParams({ stocks: next })
    } else {
      setSearchParams({})
    }
  }

  const items = data?.items ?? []

  return (
    <PageContainer>
      <div>
        <h1 className="text-xl font-bold mb-1">기업 비교 (VS 모드)</h1>
        <p className="text-sm text-muted-foreground">2~5개 기업의 주요 지표를 나란히 비교합니다.</p>
      </div>

      <Card className="p-4">
        <CompanySelector selected={selected} onAdd={handleAdd} onRemove={handleRemove} />
      </Card>

      {stockCodes.length < 2 && (
        <div className="text-center py-16 text-muted-foreground">
          기업을 2개 이상 선택하면 비교 테이블이 표시됩니다.
        </div>
      )}

      {stockCodes.length >= 2 && isLoading && (
        <div className="text-center py-16 text-muted-foreground">데이터를 불러오는 중...</div>
      )}

      {isError && (
        <div className="text-center py-16 text-destructive">데이터를 불러오지 못했습니다.</div>
      )}

      {items.length >= 2 && (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-32 bg-muted/50 font-semibold">지표</TableHead>
                {items.map((item) => (
                  <TableHead key={item.stock_code} className="text-center font-semibold">
                    <Link
                      to={`/analyze/${item.stock_code}/summary`}
                      className="hover:underline text-foreground"
                    >
                      {item.corp_name ?? item.stock_code}
                    </Link>
                    <div className="text-xs text-muted-foreground font-normal">{item.stock_code}</div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {METRICS.map((metric) => {
                const bestIdx = getBestIndex(
                  items as unknown as Record<string, unknown>[],
                  metric.key,
                  metric.higherIsBetter
                )
                return (
                  <TableRow key={metric.key}>
                    <TableCell className="font-medium text-muted-foreground bg-muted/30 text-sm">
                      {metric.label}
                    </TableCell>
                    {items.map((item, idx) => {
                      const isBest = idx === bestIdx
                      const value = item[metric.key as keyof typeof item] as number | null | undefined
                      return (
                        <TableCell
                          key={item.stock_code}
                          className={cn(
                            "text-center text-sm",
                            isBest && "font-bold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400"
                          )}
                        >
                          {metric.format(value)}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Card>
      )}
    </PageContainer>
  )
}
