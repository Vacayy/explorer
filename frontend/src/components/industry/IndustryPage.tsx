import { useState, useMemo } from "react"
import api from "@/api/client"
import {
  useIndustryGroups,
  useIndustryDetail,
  useFetchIndustryPrices,
  useCreateGroup,
  useProposeMembers,
  useAddMember,
} from "@/hooks/useIndustry"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { PageContainer } from '@/components/shared/PageContainer'
import { formatKrw, formatNumber } from "@/utils/format"
import type { Company, IndustryMember, IndustryCandidate } from "@/types"
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

  // Curation: create group dialog
  const [createOpen, setCreateOpen] = useState(false)
  const [groupName, setGroupName] = useState("")
  const [groupDesc, setGroupDesc] = useState("")
  const createGroup = useCreateGroup()

  // Curation: propose members dialog
  const [proposeOpen, setProposeOpen] = useState(false)
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [cats, setCats] = useState<Record<string, string>>({})
  const { data: candidates = [], isLoading: candidatesLoading } = useProposeMembers(
    selectedGroupId,
    proposeOpen
  )
  const addMember = useAddMember(selectedGroupId ?? 0)
  const [adding, setAdding] = useState(false)

  // Auto-select first group
  if (selectedGroupId === null && groups.length > 0) {
    setSelectedGroupId(groups[0].id)
  }

  const handleCreateGroup = async () => {
    const name = groupName.trim()
    if (!name) return
    const group = await createGroup.mutateAsync({
      name,
      description: groupDesc.trim() || undefined,
    })
    setSelectedGroupId(group.id)
    setCreateOpen(false)
    setGroupName("")
    setGroupDesc("")
  }

  const openPropose = () => {
    setChecked({})
    setCats({})
    setProposeOpen(true)
  }

  const catFor = (stockCode: string) => cats[stockCode] ?? "기타"

  const handleAddSelected = async () => {
    const picked = candidates.filter((c) => checked[c.stock_code])
    if (picked.length === 0) return
    setAdding(true)
    try {
      for (const c of picked) {
        await addMember.mutateAsync({ stock_code: c.stock_code, category: catFor(c.stock_code) })
      }
      setProposeOpen(false)
    } finally {
      setAdding(false)
    }
  }

  const checkedCount = candidates.filter((c) => checked[c.stock_code]).length

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

        <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)}>
          새 산업 그룹
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={openPropose}
          disabled={!selectedGroupId}
        >
          종목 후보 제안
        </Button>

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

      {/* Create group dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>새 산업 그룹</DialogTitle>
            <DialogDescription>밸류체인 맵을 그릴 새 산업 그룹을 만듭니다.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">이름</label>
              <Input
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder="예: 이차전지"
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">설명 (선택)</label>
              <Input
                value={groupDesc}
                onChange={(e) => setGroupDesc(e.target.value)}
                placeholder="한 줄 설명"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)}>
              취소
            </Button>
            <Button
              size="sm"
              onClick={handleCreateGroup}
              disabled={!groupName.trim() || createGroup.isPending}
            >
              {createGroup.isPending ? "생성 중..." : "생성"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Propose members dialog */}
      <Dialog open={proposeOpen} onOpenChange={setProposeOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>종목 후보 제안</DialogTitle>
            <DialogDescription>
              기계가 제안한 후보입니다. 노이즈가 섞일 수 있으니 체크로 거르고 밸류체인 단계를 지정하세요.
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-[52vh] overflow-y-auto -mx-1 px-1">
            {candidatesLoading ? (
              <div className="flex flex-col gap-2 py-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="h-12 rounded-md bg-muted/40 animate-pulse" />
                ))}
              </div>
            ) : candidates.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">제안할 후보 없음</p>
            ) : (
              <div className="flex flex-col divide-y divide-border/50">
                {candidates.map((c) => (
                  <CandidateRow
                    key={c.stock_code}
                    c={c}
                    checked={!!checked[c.stock_code]}
                    onToggle={(v) => setChecked((prev) => ({ ...prev, [c.stock_code]: v }))}
                    category={catFor(c.stock_code)}
                    onCategory={(v) => setCats((prev) => ({ ...prev, [c.stock_code]: v }))}
                  />
                ))}
              </div>
            )}
          </div>

          <DialogFooter>
            <span className="mr-auto text-xs text-muted-foreground self-center">
              {checkedCount}개 선택됨
            </span>
            <Button variant="outline" size="sm" onClick={() => setProposeOpen(false)}>
              취소
            </Button>
            <Button size="sm" onClick={handleAddSelected} disabled={checkedCount === 0 || adding}>
              {adding ? "추가 중..." : "선택 추가"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}

const CHAIN_STAGES = ["소재", "부품", "장비", "완제품", "서비스", "기타"]

/** One candidate row: checkbox + name + metric badges + value-chain stage select */
function CandidateRow({
  c,
  checked,
  onToggle,
  category,
  onCategory,
}: {
  c: IndustryCandidate
  checked: boolean
  onToggle: (v: boolean) => void
  category: string
  onCategory: (v: string) => void
}) {
  return (
    <div className="flex items-center gap-3 py-2">
      <Checkbox checked={checked} onCheckedChange={(v) => onToggle(v === true)} />
      <button
        type="button"
        className="flex items-center gap-3 flex-1 min-w-0 text-left cursor-pointer"
        onClick={() => onToggle(!checked)}
      >
        <span className="font-medium text-sm w-28 shrink-0 truncate">{c.name}</span>
        <div className="flex flex-wrap items-center gap-1.5 flex-1">
          {c.rs_short != null && <Badge variant="secondary">RS {Math.round(c.rs_short)}</Badge>}
          <Badge variant="secondary">관련도 {Math.round(c.relevance * 100)}%</Badge>
          {c.pos_52w != null && <Badge variant="outline">52주 {Math.round(c.pos_52w)}%</Badge>}
          {c.per != null && <Badge variant="outline">PER {c.per.toFixed(1)}</Badge>}
          {c.market_cap != null && <Badge variant="outline">{formatKrw(c.market_cap)}</Badge>}
        </div>
      </button>
      <Select value={category} onValueChange={onCategory}>
        <SelectTrigger className="w-[104px] shrink-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {CHAIN_STAGES.map((s) => (
            <SelectItem key={s} value={s}>{s}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
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
