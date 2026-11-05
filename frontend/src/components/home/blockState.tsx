import { AlertTriangle, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { toApiError } from "@/api/errors"

/** 등락 색 — 한국 컨벤션(상승=빨강 text-up-ink, 하락=파랑 text-down-ink) */
export const tone = (v: number | null | undefined) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up-ink" : "text-down-ink"

/** 블록 단위 오류 (상태 시트 §4.28) — 이 블록만 오류로 두고 나머지 화면은 그대로 */
export function BlockError({ message, error, onRetry }: { message: string; error?: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="space-y-2 border bg-muted/40 p-3 text-sm">
      <p className="flex items-center gap-1.5"><AlertTriangle className="size-3.5 shrink-0 text-muted-foreground" />{message}</p>
      <div className="flex items-center gap-2">
        {onRetry && <Button variant="outline" size="sm" className="h-7" onClick={onRetry}><RefreshCw className="size-3" />다시 시도</Button>}
        {error != null && <Tooltip>
          <TooltipTrigger asChild><Button variant="ghost" size="sm" className="h-7 text-muted-foreground">자세히</Button></TooltipTrigger>
          <TooltipContent className="max-w-[320px] text-xs">{toApiError(error).message}</TooltipContent>
        </Tooltip>}
      </div>
    </div>
  )
}

/** 표 모양 스켈레톤 — 실제 줄 수만큼 */
export function RowsSkeleton({ rows = 6, head = true }: { rows?: number; head?: boolean }) {
  return (
    <div role="status" aria-label="데이터 불러오는 중" aria-busy="true" className="space-y-2">
      {head && <Skeleton className="h-4 w-2/3" />}
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-6 w-full" />)}
    </div>
  )
}
