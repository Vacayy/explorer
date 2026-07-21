import { useState, useMemo } from "react"
import api from "@/api/client"
import { useIndustryGroups, useIndustryDetail, useFetchIndustryPrices } from "@/hooks/useIndustry"
import { Button } from "@/components/ui/button"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { PageContainer } from '@/components/shared/PageContainer'
import { formatKrw, formatNumber } from "@/utils/format"
import type { Company, IndustryMember } from "@/types"
import ValueChainMap from "./ValueChainMap"

interface Props {
  onSelectCompany: (company: Company) => void
}

export default function IndustryPage({ onSelectCompany }: Props) {
  const { data: groups = [] } = useIndustryGroups()
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(groups[0]?.id ?? null)
  const { data: detail, isLoading } = useIndustryDetail(selectedGroupId)
  const fetchPrices = useFetchIndustryPrices(selectedGroupId ?? 0)

  const [viewMode, setViewMode] = useState<"table" | "map">("map")
  const [sortBy, setSortBy] = useState<"market_cap" | "name">("market_cap")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  // Auto-select first group
  if (selectedGroupId === null && groups.length > 0) {
    setSelectedGroupId(groups[0].id)
  }

  // Group members by category, sort by market cap within
  const grouped = useMemo(() => {
    if (!detail) return {}
    const result: Record<string, IndustryMember[]> = {}
    for (const m of detail.members) {
      if (!result[m.category]) result[m.category] = []
      result[m.category].push(m)
    }
    // Sort within each category
    for (const cat of Object.keys(result)) {
      result[cat].sort((a, b) => {
        if (sortBy === "market_cap") {
          const aVal = a.latest_market_cap ?? 0
          const bVal = b.latest_market_cap ?? 0
          return sortDir === "desc" ? bVal - aVal : aVal - bVal
        }
        return sortDir === "desc"
          ? b.corp_name.localeCompare(a.corp_name)
          : a.corp_name.localeCompare(b.corp_name)
      })
    }
    return result
  }, [detail, sortBy, sortDir])

  // Category order by total market cap
  const categoryOrder = useMemo(() => {
    return Object.entries(grouped)
      .map(([cat, members]) => ({
        cat,
        totalMcap: members.reduce((sum, m) => sum + (m.latest_market_cap ?? 0), 0),
        count: members.length,
      }))
      .sort((a, b) => b.totalMcap - a.totalMcap)
  }, [grouped])

  const toggleSort = (col: "market_cap" | "name") => {
    if (sortBy === col) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortBy(col)
      setSortDir(col === "market_cap" ? "desc" : "asc")
    }
  }

  const handleCompanyClick = async (m: IndustryMember) => {
    // Fetch corp_code from API
    try {
      const { data } = await api.get(`/api/companies/${m.stock_code}`)
      onSelectCompany(data)
    } catch {
      // Fallback without corp_code
      onSelectCompany({
        corp_code: "",
        corp_name: m.corp_name,
        stock_code: m.stock_code,
        market: null,
        sector: null,
      })
    }
  }

  return (
    <PageContainer gap="sm">
      {/* Controls */}
      <div className="flex items-center gap-3">
        <Select
          value={selectedGroupId?.toString() ?? ""}
          onValueChange={(v) => setSelectedGroupId(parseInt(v))}
        >
          <SelectTrigger className="w-[240px]">
            <SelectValue placeholder="산업그룹 선택" />
          </SelectTrigger>
          <SelectContent>
            {groups.map((g) => (
              <SelectItem key={g.id} value={String(g.id)}>{g.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          variant="outline"
          size="sm"
          onClick={() => fetchPrices.mutate()}
          disabled={fetchPrices.isPending || !selectedGroupId}
        >
          {fetchPrices.isPending ? "가격 업데이트 중..." : "시세 업데이트"}
        </Button>

        <div className="ml-auto flex items-center gap-2">
          {detail && (
            <span className="text-xs text-muted-foreground mr-2">
              {detail.members.length}개 종목
            </span>
          )}
          <SegmentTabs
            tabs={[
              { value: "map", label: "밸류체인맵" },
              { value: "table", label: "테이블" },
            ]}
            value={viewMode}
            onChange={(v) => setViewMode(v as "table" | "map")}
          />
        </div>
      </div>

      {detail?.group.description && (
        <p className="text-xs text-muted-foreground">{detail.group.description}</p>
      )}

      {isLoading && <p className="text-muted-foreground">로딩 중...</p>}

      {/* Value Chain Map view */}
      {viewMode === "map" && detail && detail.members.length > 0 && (
        <ValueChainMap members={detail.members} onSelectCompany={(m) => handleCompanyClick(m)} />
      )}

      {/* Excel-style screener table */}
      {viewMode === "table" && categoryOrder.length > 0 && (
        <div className="border rounded-lg overflow-hidden bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 border-b-2">
                <Th>카테고리</Th>
                <Th className="cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("name")}>
                  종목명 {sortBy === "name" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                </Th>
                <Th className="text-center w-[72px]">코드</Th>
                <Th className="text-right w-[88px]">현재가</Th>
                <Th className="text-right w-[100px] cursor-pointer hover:text-foreground select-none" onClick={() => toggleSort("market_cap")}>
                  시가총액 {sortBy === "market_cap" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                </Th>
                <Th className="text-right w-[64px]">PER</Th>
                <Th className="text-right w-[64px]">PBR</Th>
                <Th className="text-right w-[72px]">영업이익률</Th>
                <Th className="text-right w-[72px]">매출성장률</Th>
                <Th className="text-right w-[72px]">영익성장률</Th>
                <Th className="text-right w-[56px]">ROE</Th>
              </tr>
            </thead>
            <tbody>
              {categoryOrder.map(({ cat, totalMcap, count }) => (
                <>
                  <tr key={`cat-${cat}`} className="bg-muted/30">
                    <td colSpan={5} className="px-2.5 py-1.5 font-semibold text-xs text-secondary-foreground">
                      {cat} <span className="font-normal text-muted-foreground">({count})</span>
                    </td>
                    <td className="px-2.5 py-1.5 text-right text-xs text-muted-foreground" colSpan={6}>
                      합계 {totalMcap > 0 ? formatKrw(totalMcap) : ""}
                    </td>
                  </tr>
                  {grouped[cat].map((m, idx) => (
                    <tr
                      key={m.id}
                      className={cn(
                        "border-b border-border/50 hover:bg-accent/50 transition-colors cursor-pointer",
                        idx % 2 === 0 ? "bg-card" : "bg-muted/10"
                      )}
                      onClick={() => handleCompanyClick(m)}
                    >
                      <td className="px-2.5 py-1.5" />
                      <td className="px-2.5 py-1.5 font-medium">{m.corp_name}</td>
                      <td className="px-2.5 py-1.5 text-center text-muted-foreground font-mono text-[11px]">{m.stock_code}</td>
                      <Num value={m.latest_close} fmt={(v) => formatNumber(v)} />
                      <Num value={m.latest_market_cap} fmt={(v) => formatKrw(v)} />
                      <Num value={m.per} fmt={(v) => `${v.toFixed(1)}`} />
                      <Num value={m.pbr} fmt={(v) => `${v.toFixed(2)}`} />
                      <HeatNum value={m.op_margin} fmt={(v) => `${v.toFixed(1)}%`} />
                      <HeatNum value={m.revenue_growth} fmt={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`} />
                      <HeatNum value={m.op_profit_growth} fmt={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`} />
                      <HeatNum value={m.roe} fmt={(v) => `${v.toFixed(1)}%`} />
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageContainer>
  )
}

/** Table header cell */
function Th({ className, children, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th className={cn("px-2.5 py-2 text-left font-semibold text-[11px] text-muted-foreground whitespace-nowrap", className)} {...props}>
      {children}
    </th>
  )
}

/** Plain numeric table cell */
function Num({ value, fmt }: { value: number | null; fmt: (v: number) => string }) {
  return (
    <td className="px-2.5 py-1.5 text-right font-mono tabular-nums text-[12px]">
      {value != null ? fmt(value) : <span className="text-muted-foreground/50">-</span>}
    </td>
  )
}

/** Heatmap-colored numeric cell: green for high positive, red for negative */
function HeatNum({ value, fmt }: { value: number | null; fmt: (v: number) => string }) {
  if (value == null) {
    return <td className="px-2.5 py-1.5 text-right text-[12px] text-muted-foreground/50">-</td>
  }

  // Color intensity based on value
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
