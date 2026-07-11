import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Search } from "lucide-react"
import { useWatchlist } from "@/hooks/useWatchlist"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { PageContainer } from "@/components/shared/PageContainer"
import { formatNumber, formatPercent } from "@/utils/format"
import { cn } from "@/lib/utils"
import type { WatchlistItem } from "@/types"

/**
 * /stocks — 종목 진입 허브 (L1 '종목').
 * 워치리스트가 기본 목록, 검색으로 전체 상장사 진입. 클릭 = 종목 홈.
 */
export default function StocksPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState("")
  const { data: items = [], isLoading } = useWatchlist()
  const { data: results = [] } = useCompanySearch(query)

  const go = (stockCode: string) => navigate(`/analyze/${stockCode}/summary`)

  return (
    <PageContainer width="reading">
      <h2 className="text-xl font-bold">종목</h2>

      {/* 검색 — 전체 상장사 */}
      <div className="relative max-w-md">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="기업명 또는 종목코드 검색…" className="pl-8 h-9" autoFocus />
        {query.trim().length >= 1 && results.length > 0 && (
          <Card className="absolute z-10 mt-1 w-full">
            <CardContent className="py-1 px-0">
              {results.slice(0, 8).map((c) => (
                <button key={c.corp_code}
                  onClick={() => c.stock_code && go(c.stock_code)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted/60 text-left">
                  <span className="font-medium">{c.corp_name}</span>
                  <span className="ml-auto text-xs text-muted-foreground tabular-nums">{c.stock_code}</span>
                </button>
              ))}
            </CardContent>
          </Card>
        )}
      </div>

      {/* 워치리스트 */}
      <Card>
        <CardContent className="py-2 px-0">
          {isLoading && (
            <div className="px-4 py-3 space-y-2">
              <Skeleton className="h-5 w-full" /><Skeleton className="h-5 w-3/4" />
            </div>
          )}
          {!isLoading && items.length === 0 && (
            <p className="px-4 py-6 text-sm text-muted-foreground text-center">
              워치리스트가 비어 있습니다 — 위 검색으로 종목에 들어가 ★를 눌러보세요.
            </p>
          )}
          {items.map((item: WatchlistItem) => (
            <button
              key={item.id}
              onClick={() => go(item.stock_code)}
              className="flex w-full items-center gap-3 px-4 py-2.5 hover:bg-muted/50 text-left border-b border-border/50 last:border-0"
            >
              <span className="text-amber-400 text-[10px] tracking-tighter shrink-0">
                {"★".repeat(item.conviction)}{"☆".repeat(5 - item.conviction)}
              </span>
              <span className="text-sm font-medium">{item.corp_name}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{item.stock_code}</span>
              <span className="ml-auto text-xs tabular-nums">
                {item.latest_close != null ? formatNumber(item.latest_close) : "-"}
              </span>
              {item.gap_pct != null && (
                <span className={cn("text-xs font-medium tabular-nums w-16 text-right",
                  item.gap_pct >= 0 ? "text-emerald-500" : "text-rose-500")}>
                  {formatPercent(item.gap_pct)}
                </span>
              )}
            </button>
          ))}
        </CardContent>
      </Card>
      <p className="text-[11px] text-muted-foreground">
        갭 = 목표가 대비 현재가 괴리. 팔로우 레일(우측 엣지)과 ⌘K에서도 진입할 수 있습니다.
      </p>
    </PageContainer>
  )
}
