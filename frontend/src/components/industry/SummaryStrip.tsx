import type { ReactNode } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export interface SummaryCell {
  label: string
  value: ReactNode
  sub?: ReactNode
  /** 값 글자색(등락 등) */
  className?: string
}

/** 산업 화면 머리의 요약 줄 (시안 Industry-Trade·ValueChain·Credit) — 칸 네 개(인물 홈은 세 개), 좁은 화면은 두 칸씩 */
export function SummaryStrip({ cells, label, cols = 4 }: { cells: SummaryCell[]; label: string; cols?: 3 | 4 }) {
  return <div data-summary={label} className={cn("grid grid-cols-2 border bg-card", cols === 3 ? "md:grid-cols-3" : "md:grid-cols-4")}>
    {cells.map(c => <div key={c.label} className="min-w-0 border-b p-4 max-md:[&:nth-child(odd)]:border-r md:border-b-0 md:border-r md:last:border-r-0">
      <div className="truncate text-xs text-muted-foreground">{c.label}</div>
      <div className={cn("mt-1 truncate font-mono text-2xl tabular-nums", c.className)}>{c.value}</div>
      {c.sub != null && <div className="mt-1 truncate text-caption text-muted-foreground">{c.sub}</div>}
    </div>)}
  </div>
}

export function SummaryStripSkeleton() {
  return <div role="status" aria-label="요약 불러오는 중" className="grid grid-cols-2 gap-px border bg-card md:grid-cols-4">
    {Array.from({ length: 4 }, (_, i) => <div key={i} className="space-y-2 p-4"><Skeleton className="h-3 w-20" /><Skeleton className="h-7 w-24" /><Skeleton className="h-3 w-16" /></div>)}
  </div>
}
