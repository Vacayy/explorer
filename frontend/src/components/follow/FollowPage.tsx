import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Search, X } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { unfollowEntity, spineKeys } from "@/api/spine"
import { useDefaultWatchGroup, useRemoveMember, useUpdateMember } from "@/hooks/useGroups"
import { useQuotes, type LiveQuote } from "@/hooks/useQuotes"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { PageLayout, PageHeader } from "@/components/shared/PageLayout"
import { Button } from "@/components/ui/button"
import { formatKrw, formatNumber } from "@/utils/format"
import { ErrorState } from "@/components/shared/ErrorState"
import type { StockGroupMember } from "@/types"

/**
 * /follow — 팔로우 허브 (L1). 내가 따라가는 종목·인물.
 * 행 클릭 = 도시에 (종목→/analyze, 인물→/person).
 * 새 소스 종류(유튜브·리포트 등)가 늘면 여기에 섹션이 추가된다.
 */
export default function FollowPage() {
  const navigate = useNavigate()
  return <PageLayout header={<PageHeader title="관심목록" description="추적하는 기업·인물" actions={<Button asChild variant="outline" size="sm"><Link to="/admin/sources">소스 관리</Link></Button>} />}>
    <div className="surface-stack">
      <StocksSection onGo={code => navigate(`/analyze/${code}/summary`)} />
      <FollowedPeopleCard onGo={name => navigate(`/person?name=${encodeURIComponent(name)}`)} />
    </div>
  </PageLayout>
}

/* ── 종목 (기본 관심 묶음 '관심 종목': 정렬·편집·삭제 + 전체 검색) ── */

type SortKey = "name" | "close" | "market_cap"

function StocksSection({ onGo }: { onGo: (code: string) => void }) {
  const [query, setQuery] = useState("")
  const [sortKey, setSortKey] = useState<SortKey>("market_cap")
  const [sortAsc, setSortAsc] = useState(false)
  const [editingCode, setEditingCode] = useState<string | null>(null)
  const group = useDefaultWatchGroup()
  const items = group.data?.members ?? []
  const isLoading = group.isPending
  const { data: results = [] } = useCompanySearch(query)
  const update = useUpdateMember(group.data?.id ?? 0)
  const del = useRemoveMember(group.data?.id ?? 0)
  const { data: quotes } = useQuotes(items.map((i) => i.stock_code))
  const quoteMap = new Map((quotes ?? []).map((q) => [q.stock_code, q]))

  const sorted = [...items].sort((a, b) => {
    const va = a[sortKey], vb = b[sortKey]
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number)
    return sortAsc ? cmp : -cmp
  })

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(key === "name") }
  }
  const arrow = (key: SortKey) => sortKey === key ? (sortAsc ? " ↑" : " ↓") : ""

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-3">
        <CardTitle className="text-sm">종목 <span className="font-normal text-muted-foreground">{items.length}</span></CardTitle>
        <div className="relative ml-auto w-full sm:w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="전체 상장사 검색…" className="pl-8 h-8 text-sm" />
          {query.trim().length >= 1 && results.length > 0 && (
            <Card className="absolute z-10 mt-1 w-full">
              <CardContent className="py-1 px-0">
                {results.slice(0, 8).map((c) => (
                  <button key={c.corp_code}
                    onClick={() => c.stock_code && onGo(c.stock_code)}
                    className="flex w-full items-center gap-2 px-3 py-2.5 md:py-1.5 text-sm hover:bg-muted/60 text-left">
                    <span className="font-medium">{c.corp_name}</span>
                    <span className="ml-auto text-xs text-muted-foreground tabular-nums">{c.stock_code}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-0 pb-1">
        {isLoading && <div className="px-4 py-3 space-y-2"><Skeleton className="h-5 w-full" /><Skeleton className="h-5 w-3/4" /></div>}
        {group.isError && <ErrorState message="관심 종목을 불러오지 못했습니다." onRetry={() => group.refetch()} />}
        {group.data && items.length === 0 && (
          <p className="px-4 py-5 text-sm text-muted-foreground text-center">
            관심 종목이 비어 있습니다 — 검색으로 종목에 들어가 ★를 눌러보세요.
          </p>
        )}
        {items.length > 0 && (
          // 좁은 화면 — 열을 짓누르지 않고 표 단위로 가로 스크롤
          <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground whitespace-nowrap">
                <th className="px-4 py-1.5 text-left font-medium cursor-pointer select-none" onClick={() => toggleSort("name")}>
                  종목명{arrow("name")}
                </th>
                <th className="hidden py-1.5 text-left font-medium md:table-cell">코드</th>
                <th className="py-1.5 text-right font-medium cursor-pointer select-none" onClick={() => toggleSort("close")}>
                  현재가{arrow("close")}
                </th>
                <th className="pl-3 md:pl-0 py-1.5 text-right font-medium cursor-pointer select-none" onClick={() => toggleSort("market_cap")}>
                  시가총액{arrow("market_cap")}
                </th>
                <th className="pl-3 md:pl-0 py-1.5 text-right font-medium">목표가</th>
                <th className="pl-3 md:pl-0 py-1.5 text-left font-medium">논지</th>
                <th className="px-4 py-1.5 text-right font-medium w-24"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((item) => (
                <StockRow key={item.stock_code} item={item} quote={quoteMap.get(item.stock_code)}
                  editing={editingCode === item.stock_code}
                  onEdit={() => setEditingCode(editingCode === item.stock_code ? null : item.stock_code)}
                  onSaved={() => setEditingCode(null)}
                  onGo={() => onGo(item.stock_code)}
                  onDelete={() => del.mutate(item.stock_code, { onSuccess: (d) => toast.success(`'${item.name}' ‘${d.name}’에서 삭제`) })}
                  update={update}
                />
              ))}
            </tbody>
          </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function StockRow({ item, quote, editing, onEdit, onSaved, onGo, onDelete, update }: {
  item: StockGroupMember
  quote?: LiveQuote
  editing: boolean
  onEdit: () => void
  onSaved: () => void
  onGo: () => void
  onDelete: () => void
  update: ReturnType<typeof useUpdateMember>
}) {
  return (
    <>
      <tr className="border-b border-border/50 hover:bg-muted/50 cursor-pointer" onClick={onGo}>
        <td className="px-4 py-2 font-medium whitespace-nowrap">{item.name}</td>
        <td className="hidden py-2 text-xs text-muted-foreground tabular-nums md:table-cell">{item.stock_code}</td>
        <td className="py-2 text-right tabular-nums text-xs whitespace-nowrap">
          {quote?.price != null ? (
            <>
              {formatNumber(quote.price)}
              {quote.change_pct != null && (
                <span className={`ml-1.5 ${quote.change_pct >= 0 ? "text-up" : "text-down"}`}>
                  {quote.change_pct >= 0 ? "+" : ""}{quote.change_pct.toFixed(1)}%
                </span>
              )}
            </>
          ) : item.close != null ? formatNumber(item.close) : "-"}
        </td>
        <td className="pl-3 md:pl-0 py-2 text-right tabular-nums text-xs whitespace-nowrap">
          {item.market_cap != null ? formatKrw(item.market_cap) : "-"}
        </td>
        <td className="pl-3 md:pl-0 py-2 text-right tabular-nums text-xs">
          {item.target_price != null ? formatNumber(item.target_price) : "-"}
        </td>
        <td className="pl-3 md:pl-0 py-2 text-xs text-muted-foreground max-w-[240px]">
          <span className="block truncate" title={item.thesis ?? ""}>{item.thesis || "-"}</span>
        </td>
        <td className="px-4 py-2 text-right whitespace-nowrap">
          <button onClick={(e) => { e.stopPropagation(); onEdit() }}
            className="py-2.5 md:py-0 text-[11px] text-muted-foreground hover:text-foreground mr-2">편집</button>
          <button onClick={(e) => { e.stopPropagation(); onDelete() }}
            className="py-2.5 md:py-0 text-[11px] text-muted-foreground hover:text-destructive">삭제</button>
        </td>
      </tr>
      {editing && (
        <tr className="border-b border-border/50 bg-muted/30">
          <td colSpan={7} className="px-4 py-2">
            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                const fd = new FormData(e.currentTarget)
                const tp = fd.get("tp")?.toString().trim()
                update.mutate(
                  { stockCode: item.stock_code, target_price: tp ? Number(tp.replace(/,/g, "")) : undefined,
                    thesis: fd.get("thesis")?.toString() ?? undefined },
                  { onSuccess: () => { toast.success("저장됨 — 논지는 AI 브리프의 점검 대상이 됩니다"); onSaved() } },
                )
              }}
            >
              <label className="text-[11px] text-muted-foreground">목표가</label>
              <Input name="tp" defaultValue={item.target_price ?? ""} className="h-7 w-28 text-xs" placeholder="원" />
              <label className="text-[11px] text-muted-foreground">투자 논지</label>
              <Input name="thesis" defaultValue={item.thesis ?? ""} className="h-7 flex-1 min-w-[200px] text-xs"
                placeholder="핵심 논지 한 줄 — AI 브리프가 새 증거와 대조합니다" />
              <button type="submit" disabled={update.isPending}
                className="h-11 md:h-7 px-2.5 rounded-md bg-primary text-primary-foreground text-xs disabled:opacity-50">저장</button>
            </form>
          </td>
        </tr>
      )}
    </>
  )
}

/* ── 팔로우 인물 ── */

function FollowedPeopleCard({ onGo }: { onGo: (name: string) => void }) {
  const qc = useQueryClient()
  const { data: follows = [] } = useQuery({
    queryKey: ["spine", "follows"],
    queryFn: async () => (await api.get("/api/spine/follows")).data as
      { entity_id: number; type: string; name: string }[],
    staleTime: 60_000,
  })
  const people = follows.filter((f) => f.type === "person")
  const unfollow = useMutation({
    mutationFn: unfollowEntity,
    onSuccess: () => {
      toast.success("팔로우 해제")
      qc.invalidateQueries({ queryKey: ["spine", "follows"] })
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">인물 <span className="font-normal text-muted-foreground">{people.length}</span></CardTitle>
      </CardHeader>
      <CardContent>
        {people.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            팔로우한 인물이 없습니다 — 피드·문서의 인물 칩에서 프로필로 들어가 팔로우해보세요.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {people.map((f) => (
              <Badge key={f.entity_id} variant="outline" className="text-xs gap-1 pr-1 cursor-pointer text-hypothesis border-hypothesis/40 hover:bg-hypothesis/10"
                onClick={() => onGo(f.name)}>
                {f.name}
                <button
                  onClick={(e) => { e.stopPropagation(); unfollow.mutate(f.entity_id) }}
                  className="hover:text-destructive" aria-label="팔로우 해제">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
