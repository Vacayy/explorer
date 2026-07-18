import { useState, useEffect, useMemo } from "react"
import { useSearchParams, useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { useScreener } from "@/hooks/useScreener"
import type { ScreenerParams, ScreenerItem } from "@/hooks/useScreener"
import { useAddToWatchlist } from "@/hooks/useWatchlist"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { TableSkeleton } from "@/components/shared/Skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { PageContainer } from '@/components/shared/PageContainer'
import { formatKrw } from "@/utils/format"
import { cn } from "@/lib/utils"

// ─── Filter state derived from URL ───────────────────────────────────────────

function paramsToFilters(sp: URLSearchParams): FilterValues {
  return {
    per_max: sp.get("per_max") ?? "",
    pbr_max: sp.get("pbr_max") ?? "",
    opm_min: sp.get("opm_min") ?? "",
    roe_min: sp.get("roe_min") ?? "",
    rev_growth_min: sp.get("rev_growth_min") ?? "",
    mcap_tier: (sp.get("mcap_tier") as ScreenerParams["mcap_tier"]) ?? "all",
  }
}

interface FilterValues {
  per_max: string
  pbr_max: string
  opm_min: string
  roe_min: string
  rev_growth_min: string
  mcap_tier: ScreenerParams["mcap_tier"]
}

const DEFAULT_FILTERS: FilterValues = {
  per_max: "",
  pbr_max: "",
  opm_min: "",
  roe_min: "",
  rev_growth_min: "",
  mcap_tier: "all",
}

function filtersToQueryParams(f: FilterValues): ScreenerParams {
  const p: ScreenerParams = {}
  if (f.per_max !== "") p.per_max = parseFloat(f.per_max)
  if (f.pbr_max !== "") p.pbr_max = parseFloat(f.pbr_max)
  if (f.opm_min !== "") p.opm_min = parseFloat(f.opm_min)
  if (f.roe_min !== "") p.roe_min = parseFloat(f.roe_min)
  if (f.rev_growth_min !== "") p.rev_growth_min = parseFloat(f.rev_growth_min)
  if (f.mcap_tier && f.mcap_tier !== "all") p.mcap_tier = f.mcap_tier
  return p
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ScreenerPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const addToWatchlist = useAddToWatchlist()

  // Local filter state (drives inputs)
  const [filters, setFilters] = useState<FilterValues>(() => paramsToFilters(searchParams))

  // Debounced params for the actual API query
  const [debouncedParams, setDebouncedParams] = useState<ScreenerParams>(() =>
    filtersToQueryParams(paramsToFilters(searchParams))
  )

  // Sort state
  const [sortBy, setSortBy] = useState<string>("market_cap")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  // Debounce: update URL + query params 500ms after filter changes
  useEffect(() => {
    const timer = setTimeout(() => {
      const params = filtersToQueryParams(filters)
      setDebouncedParams(params)

      // Sync to URL
      const sp = new URLSearchParams()
      if (filters.per_max) sp.set("per_max", filters.per_max)
      if (filters.pbr_max) sp.set("pbr_max", filters.pbr_max)
      if (filters.opm_min) sp.set("opm_min", filters.opm_min)
      if (filters.roe_min) sp.set("roe_min", filters.roe_min)
      if (filters.rev_growth_min) sp.set("rev_growth_min", filters.rev_growth_min)
      if (filters.mcap_tier && filters.mcap_tier !== "all") sp.set("mcap_tier", filters.mcap_tier)
      setSearchParams(sp, { replace: true })
    }, 500)
    return () => clearTimeout(timer)
  }, [filters, setSearchParams])

  const queryParams: ScreenerParams = {
    ...debouncedParams,
    sort: sortBy,
    sort_dir: sortDir,
    limit: 200,
  }

  const { data, isLoading, isError, refetch } = useScreener(queryParams)

  // Client-side sort (in case server doesn't support all columns)
  const sorted = useMemo(() => {
    if (!data?.items) return []
    return [...data.items].sort((a, b) => {
      const aVal = (a as unknown as Record<string, unknown>)[sortBy] as number | null
      const bVal = (b as unknown as Record<string, unknown>)[sortBy] as number | null
      if (aVal == null && bVal == null) return 0
      if (aVal == null) return 1
      if (bVal == null) return -1
      return sortDir === "desc" ? bVal - aVal : aVal - bVal
    })
  }, [data, sortBy, sortDir])

  const toggleSort = (col: string) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortBy(col)
      setSortDir("desc")
    }
  }

  const sortIndicator = (col: string) =>
    sortBy === col ? (sortDir === "asc" ? " ▲" : " ▼") : ""

  const resetFilters = () => {
    setFilters(DEFAULT_FILTERS)
  }

  const handleRowClick = (item: ScreenerItem) => {
    navigate(`/analyze/${item.stock_code}/summary`)
  }

  const handleAddWatchlist = (e: React.MouseEvent, item: ScreenerItem) => {
    e.stopPropagation()
    addToWatchlist.mutate(
      {
        stock_code: item.stock_code,
        corp_code: "",
        corp_name: item.corp_name,
        conviction: 3,
      },
      { onSuccess: () => toast.success("워치리스트에 추가되었습니다") }
    )
  }

  return (
    <PageContainer gap="sm">
      {/* Filter Panel */}
      <div className="border rounded-lg bg-card p-4 space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          {/* PER max */}
          <FilterInput
            label="PER"
            value={filters.per_max}
            onChange={(v) => setFilters((f) => ({ ...f, per_max: v }))}
            placeholder="최대"
          />
          {/* PBR max */}
          <FilterInput
            label="PBR"
            value={filters.pbr_max}
            onChange={(v) => setFilters((f) => ({ ...f, pbr_max: v }))}
            placeholder="최대"
          />
          {/* 영업이익률 min */}
          <FilterInput
            label="영업이익률"
            value={filters.opm_min}
            onChange={(v) => setFilters((f) => ({ ...f, opm_min: v }))}
            placeholder="최소 %"
          />
          {/* ROE min */}
          <FilterInput
            label="ROE"
            value={filters.roe_min}
            onChange={(v) => setFilters((f) => ({ ...f, roe_min: v }))}
            placeholder="최소 %"
          />
          {/* 매출성장률 min */}
          <FilterInput
            label="매출성장률"
            value={filters.rev_growth_min}
            onChange={(v) => setFilters((f) => ({ ...f, rev_growth_min: v }))}
            placeholder="최소 %"
          />
          {/* 시가총액 select */}
          <div className="flex flex-col gap-1">
            <Label className="text-[11px] font-medium text-muted-foreground">시가총액</Label>
            <Select
              value={filters.mcap_tier ?? "all"}
              onValueChange={(v) =>
                setFilters((f) => ({ ...f, mcap_tier: v as ScreenerParams["mcap_tier"] }))
              }
            >
              <SelectTrigger className="w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">전체</SelectItem>
                <SelectItem value="small">소형(&lt;3천억)</SelectItem>
                <SelectItem value="mid">중형</SelectItem>
                <SelectItem value="large">대형(&gt;2조)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Reset + count */}
          <div className="ml-auto flex items-end gap-3">
            <Button variant="outline" size="sm" onClick={resetFilters}>
              필터 초기화
            </Button>
          </div>
        </div>

        {/* Match count */}
        {data && (
          <p className="text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">{data.total.toLocaleString("ko-KR")}건 매칭</span>
            {" / 전체 "}
            {data.filtered_from.toLocaleString("ko-KR")}건
          </p>
        )}
      </div>

      {/* Result Table */}
      {isLoading && <TableSkeleton rows={10} />}

      {isError && <ErrorState onRetry={() => refetch()} />}

      {!isLoading && !isError && sorted.length === 0 && (
        <div className="py-16 text-center space-y-3">
          <p className="text-muted-foreground text-sm">조건에 맞는 종목이 없습니다. 필터를 완화해보세요.</p>
          <Button variant="outline" size="sm" onClick={resetFilters}>필터 초기화</Button>
        </div>
      )}

      {!isLoading && !isError && sorted.length > 0 && (
        <div className="border rounded-lg overflow-hidden bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 border-b-2">
                <Th className="cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("corp_name")}>
                  종목명{sortIndicator("corp_name")}
                </Th>
                <Th className="text-center w-[72px]">코드</Th>
                <Th className="text-right w-[100px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("market_cap")}>
                  시총{sortIndicator("market_cap")}
                </Th>
                <Th className="text-right w-[64px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("per")}>
                  PER{sortIndicator("per")}
                </Th>
                <Th className="text-right w-[64px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("pbr")}>
                  PBR{sortIndicator("pbr")}
                </Th>
                <Th className="text-right w-[80px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("op_margin")}>
                  영업이익률{sortIndicator("op_margin")}
                </Th>
                <Th className="text-right w-[80px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("revenue_growth")}>
                  매출성장률{sortIndicator("revenue_growth")}
                </Th>
                <Th className="text-right w-[80px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("op_profit_growth")}>
                  영익성장률{sortIndicator("op_profit_growth")}
                </Th>
                <Th className="text-right w-[64px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("roe")}>
                  ROE{sortIndicator("roe")}
                </Th>
                <Th className="w-[64px]" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((item, idx) => (
                <tr
                  key={item.stock_code}
                  className={cn(
                    "border-b border-border/50 hover:bg-accent/50 transition-colors cursor-pointer",
                    idx % 2 === 0 ? "bg-card" : "bg-muted/10"
                  )}
                  onClick={() => handleRowClick(item)}
                >
                  <td className="px-2.5 py-1.5 font-medium">{item.corp_name}</td>
                  <td className="px-2.5 py-1.5 text-center text-muted-foreground font-mono text-[11px]">{item.stock_code}</td>
                  <Num value={item.market_cap} fmt={(v) => formatKrw(v)} />
                  <Num value={item.per} fmt={(v) => v.toFixed(1)} />
                  <Num value={item.pbr} fmt={(v) => v.toFixed(2)} />
                  <HeatNum value={item.op_margin} fmt={(v) => `${v.toFixed(1)}%`} />
                  <HeatNum value={item.revenue_growth} fmt={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`} />
                  <HeatNum value={item.op_profit_growth} fmt={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`} />
                  <HeatNum value={item.roe} fmt={(v) => `${v.toFixed(1)}%`} />
                  <td className="px-2 py-1.5 text-center">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-[11px] text-muted-foreground hover:text-foreground"
                      onClick={(e) => handleAddWatchlist(e, item)}
                    >
                      + 워치
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageContainer>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function FilterInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      <Input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-[96px] h-9"
      />
    </div>
  )
}

function Th({ className, children, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "px-2.5 py-2 text-left font-semibold text-[11px] text-muted-foreground whitespace-nowrap",
        className
      )}
      {...props}
    >
      {children}
    </th>
  )
}

function Num({ value, fmt }: { value: number | null; fmt: (v: number) => string }) {
  return (
    <td className="px-2.5 py-1.5 text-right font-mono tabular-nums text-[12px]">
      {value != null ? fmt(value) : <span className="text-muted-foreground/50">-</span>}
    </td>
  )
}

function HeatNum({ value, fmt }: { value: number | null; fmt: (v: number) => string }) {
  if (value == null) {
    return <td className="px-2.5 py-1.5 text-right text-[12px] text-muted-foreground/50">-</td>
  }

  let bg = ""
  if (value > 30) bg = "bg-emerald-100 text-emerald-800"
  else if (value > 15) bg = "bg-emerald-50 text-emerald-700"
  else if (value > 0) bg = "bg-emerald-50/50 text-emerald-600"
  else if (value > -10) bg = "bg-rose-50/50 text-rose-600"
  else if (value > -30) bg = "bg-rose-50 text-rose-700"
  else bg = "bg-rose-100 text-rose-800"

  return (
    <td className={cn("px-2.5 py-1.5 text-right font-mono tabular-nums text-[12px] font-medium", bg)}>
      {fmt(value)}
    </td>
  )
}
