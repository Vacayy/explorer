import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { useWatchlist, useAddToWatchlist, useUpdateWatchlistItem, useDeleteWatchlistItem } from "@/hooks/useWatchlist"
import { formatKrw, formatNumber, formatPercent } from "@/utils/format"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table"
import CompanySearchCombobox from "@/components/shared/CompanySearchCombobox"
import type { WatchlistItem } from "@/types"
import type { Company } from "@/types"

type SortKey = "created_at" | "conviction" | "gap_pct" | "latest_market_cap"

function gapColor(gap: number | null): string {
  if (gap === null) return "text-muted-foreground"
  if (gap >= 30) return "text-emerald-600"
  if (gap >= 10) return "text-emerald-500"
  if (gap >= 0) return "text-emerald-400"
  if (gap >= -10) return "text-rose-400"
  return "text-rose-600"
}

function ConvictionStars({
  value,
  onClick,
}: {
  value: number
  onClick?: (n: number) => void
}) {
  return (
    <span className="text-amber-400 text-sm tracking-tighter whitespace-nowrap">
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={cn(onClick && "cursor-pointer hover:scale-110 inline-block transition-transform")}
          onClick={onClick ? (e) => { e.stopPropagation(); onClick(n) } : undefined}
        >
          {n <= value ? "★" : "☆"}
        </span>
      ))}
    </span>
  )
}

interface EditState {
  id: number
  conviction: number
  target_price: string
  thesis: string
}

export default function WatchlistPage() {
  const navigate = useNavigate()
  const { data: items = [], isLoading } = useWatchlist()
  const addItem = useAddToWatchlist()
  const updateItem = useUpdateWatchlistItem()
  const deleteItem = useDeleteWatchlistItem()

  // Sort state
  const [sortKey, setSortKey] = useState<SortKey>("created_at")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  // Add form state
  const [showAddForm, setShowAddForm] = useState(false)
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null)
  const [addConviction, setAddConviction] = useState(3)
  const [addTargetPrice, setAddTargetPrice] = useState("")
  const [addThesis, setAddThesis] = useState("")

  // Edit state
  const [editState, setEditState] = useState<EditState | null>(null)

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const sortedItems = [...items].sort((a, b) => {
    let aVal: number
    let bVal: number
    if (sortKey === "created_at") {
      aVal = new Date(a.created_at).getTime()
      bVal = new Date(b.created_at).getTime()
    } else {
      aVal = (a[sortKey] as number | null) ?? -Infinity
      bVal = (b[sortKey] as number | null) ?? -Infinity
    }
    return sortDir === "desc" ? bVal - aVal : aVal - bVal
  })

  const handleAdd = async () => {
    if (!selectedCompany) return
    await addItem.mutateAsync({
      stock_code: selectedCompany.stock_code!,
      corp_code: selectedCompany.corp_code,
      corp_name: selectedCompany.corp_name,
      conviction: addConviction,
      target_price: addTargetPrice ? parseFloat(addTargetPrice) : null,
      thesis: addThesis || null,
    })
    toast.success("워치리스트에 추가되었습니다")
    setShowAddForm(false)
    setSelectedCompany(null)
    setAddConviction(3)
    setAddTargetPrice("")
    setAddThesis("")
  }

  const handleUpdateConviction = (item: WatchlistItem, conviction: number) => {
    updateItem.mutate({ id: item.id, conviction })
  }

  const startEdit = (item: WatchlistItem) => {
    setEditState({
      id: item.id,
      conviction: item.conviction,
      target_price: item.target_price != null ? String(item.target_price) : "",
      thesis: item.thesis ?? "",
    })
  }

  const handleSaveEdit = async () => {
    if (!editState) return
    await updateItem.mutateAsync({
      id: editState.id,
      conviction: editState.conviction,
      target_price: editState.target_price ? parseFloat(editState.target_price) : null,
      thesis: editState.thesis || null,
    })
    setEditState(null)
  }

  const SortBtn = ({ label, k }: { label: string; k: SortKey }) => (
    <Button
      variant="outline"
      size="xs"
      onClick={() => handleSort(k)}
      className={cn(
        sortKey === k
          ? "border-primary text-primary bg-primary/5"
          : "border-border text-muted-foreground hover:text-foreground"
      )}
    >
      {label} {sortKey === k ? (sortDir === "asc" ? "▲" : "▼") : ""}
    </Button>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">워치리스트</h1>
        <Button size="sm" onClick={() => setShowAddForm((v) => !v)}>
          + 종목 추가
        </Button>
      </div>

      {/* Add form */}
      {showAddForm && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            <CompanySearchCombobox
              value={selectedCompany}
              onSelect={setSelectedCompany}
              placeholder="종목명 또는 코드 검색..."
              className="w-full"
            />

            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-16">확신도</span>
              <ConvictionStars value={addConviction} onClick={setAddConviction} />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-16">목표가</span>
              <Input
                className="max-w-[160px]"
                placeholder="예: 85000"
                value={addTargetPrice}
                onChange={(e) => setAddTargetPrice(e.target.value)}
                type="number"
              />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-16">투자논점</span>
              <Input
                placeholder="간단한 투자 논점..."
                value={addThesis}
                onChange={(e) => setAddThesis(e.target.value)}
              />
            </div>

            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" onClick={() => setShowAddForm(false)}>
                취소
              </Button>
              <Button
                size="sm"
                onClick={handleAdd}
                disabled={!selectedCompany || addItem.isPending}
              >
                {addItem.isPending ? "추가 중..." : "추가"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sort buttons */}
      <div className="flex gap-2 items-center">
        <span className="text-xs text-muted-foreground">정렬:</span>
        <SortBtn label="추가일" k="created_at" />
        <SortBtn label="확신도" k="conviction" />
        <SortBtn label="갭률" k="gap_pct" />
        <SortBtn label="시가총액" k="latest_market_cap" />
      </div>

      {/* Table */}
      {isLoading ? (
        <p className="text-muted-foreground text-sm py-8 text-center">로딩 중...</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground text-sm py-12 text-center">
          관심 종목을 추가해보세요
        </p>
      ) : (
        <div className="border rounded-lg overflow-hidden bg-card overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead className="text-[11px] w-[100px]">확신도</TableHead>
                <TableHead className="text-[11px]">종목명</TableHead>
                <TableHead className="text-[11px] w-[72px] text-center">코드</TableHead>
                <TableHead className="text-[11px] text-right w-[88px]">현재가</TableHead>
                <TableHead className="text-[11px] text-right w-[88px]">목표가</TableHead>
                <TableHead className="text-[11px] text-right w-[80px]">갭률</TableHead>
                <TableHead className="text-[11px] text-right w-[100px]">시가총액</TableHead>
                <TableHead className="text-[11px]">투자논점</TableHead>
                <TableHead className="text-[11px] w-[80px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedItems.map((item) => {
                const isEditing = editState?.id === item.id
                return (
                  <TableRow key={item.id} className="hover:bg-accent/40 transition-colors">
                    <TableCell>
                      {isEditing ? (
                        <ConvictionStars
                          value={editState!.conviction}
                          onClick={(n) => setEditState((s) => s ? { ...s, conviction: n } : s)}
                        />
                      ) : (
                        <ConvictionStars
                          value={item.conviction}
                          onClick={(n) => handleUpdateConviction(item, n)}
                        />
                      )}
                    </TableCell>
                    <TableCell
                      className="font-medium cursor-pointer hover:text-primary text-sm"
                      onClick={() => navigate(`/analyze/${item.stock_code}/summary`)}
                    >
                      {item.corp_name}
                    </TableCell>
                    <TableCell className="text-center text-muted-foreground font-mono text-[11px]">
                      {item.stock_code}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-[12px]">
                      {item.latest_close != null ? formatNumber(item.latest_close) : "-"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-[12px]">
                      {isEditing ? (
                        <Input
                          className="h-6 text-xs text-right w-20 ml-auto"
                          value={editState!.target_price}
                          onChange={(e) => setEditState((s) => s ? { ...s, target_price: e.target.value } : s)}
                          type="number"
                        />
                      ) : (
                        item.target_price != null ? formatNumber(item.target_price) : (
                          <span className="text-muted-foreground/50">-</span>
                        )
                      )}
                    </TableCell>
                    <TableCell className={cn("text-right font-mono tabular-nums text-[12px] font-medium", gapColor(item.gap_pct))}>
                      {item.gap_pct != null ? formatPercent(item.gap_pct) : (
                        <span className="text-muted-foreground/50">-</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-[12px]">
                      {item.latest_market_cap != null ? formatKrw(item.latest_market_cap) : (
                        <span className="text-muted-foreground/50">-</span>
                      )}
                    </TableCell>
                    <TableCell className="text-[12px] text-muted-foreground max-w-[200px]">
                      {isEditing ? (
                        <Input
                          className="h-6 text-xs"
                          value={editState!.thesis}
                          onChange={(e) => setEditState((s) => s ? { ...s, thesis: e.target.value } : s)}
                        />
                      ) : (
                        <span className="truncate block">{item.thesis ?? ""}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {isEditing ? (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[11px]"
                              onClick={handleSaveEdit}
                              disabled={updateItem.isPending}
                            >
                              저장
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[11px]"
                              onClick={() => setEditState(null)}
                            >
                              취소
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[11px] text-muted-foreground hover:text-foreground"
                              onClick={() => startEdit(item)}
                            >
                              편집
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[11px] text-muted-foreground hover:text-rose-600"
                              onClick={() => deleteItem.mutate(item.id, { onSuccess: () => toast.success("삭제되었습니다") })}
                              disabled={deleteItem.isPending}
                            >
                              삭제
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
