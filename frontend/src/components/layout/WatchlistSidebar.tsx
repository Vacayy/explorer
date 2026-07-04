import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { cn } from "@/lib/utils"
import { useWatchlist } from "@/hooks/useWatchlist"
import { formatNumber, formatPercent } from "@/utils/format"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { WatchlistItem } from "@/types"

interface Props {
  currentStockCode: string | null
}

function gapColor(gap: number | null): string {
  if (gap === null) return "text-muted-foreground"
  if (gap >= 30) return "text-emerald-600"
  if (gap >= 10) return "text-emerald-500"
  if (gap >= 0) return "text-emerald-400"
  if (gap >= -10) return "text-rose-400"
  return "text-rose-600"
}

function ConvictionStars({ value }: { value: number }) {
  return (
    <span className="text-amber-400 text-[10px] tracking-tighter">
      {"★".repeat(value)}{"☆".repeat(5 - value)}
    </span>
  )
}

export default function WatchlistSidebar({ currentStockCode }: Props) {
  const navigate = useNavigate()
  const { data: items = [] } = useWatchlist()
  const [collapsed, setCollapsed] = useState(false)

  if (collapsed) {
    return (
      <Button
        variant="ghost"
        onClick={() => setCollapsed(false)}
        className="fixed right-0 top-[120px] w-8 h-20 bg-card border border-r-0 rounded-l-lg flex items-center justify-center cursor-pointer shadow-sm text-xs text-muted-foreground"
        style={{ writingMode: "vertical-rl" }}
      >
        워치리스트
      </Button>
    )
  }

  return (
    <aside className="w-[220px] shrink-0 bg-card border-l sticky top-[110px] h-[calc(100vh-110px)] py-4">
      <ScrollArea className="h-full">
        <div className="flex items-center justify-between px-3.5 mb-3">
          <h3 className="text-xs font-semibold text-secondary-foreground">워치리스트</h3>
          <div className="flex gap-2 items-center">
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => navigate("/research/watchlist")}
              className="text-[11px] text-muted-foreground hover:text-foreground font-semibold"
              title="워치리스트 전체 보기"
            >
              +
            </Button>
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => setCollapsed(true)}
              className="text-muted-foreground hover:text-foreground text-sm leading-none"
            >
              ✕
            </Button>
          </div>
        </div>

        {items.length === 0 && (
          <p className="px-3.5 py-8 text-xs text-muted-foreground text-center">
            관심 종목을 추가해보세요
          </p>
        )}

        {items.map((item: WatchlistItem) => {
          const isActive = item.stock_code === currentStockCode
          return (
            <div
              key={item.id}
              onClick={() => navigate(`/analyze/${item.stock_code}/summary`)}
              className={cn(
                "flex items-center justify-between px-3.5 py-2.5 cursor-pointer border-l-[3px] transition-colors",
                isActive
                  ? "bg-accent border-l-primary"
                  : "border-l-transparent hover:bg-muted/50"
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1 mb-0.5">
                  <ConvictionStars value={item.conviction} />
                </div>
                <div className={cn(
                  "text-[13px] truncate",
                  isActive ? "font-semibold text-primary" : "text-foreground"
                )}>
                  {item.corp_name}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[11px] text-muted-foreground">
                    {item.latest_close != null ? formatNumber(item.latest_close) : "-"}
                  </span>
                  {item.gap_pct != null && (
                    <span className={cn("text-[11px] font-medium", gapColor(item.gap_pct))}>
                      {formatPercent(item.gap_pct)}
                    </span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </ScrollArea>
    </aside>
  )
}
