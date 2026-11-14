import { cn } from "@/lib/utils"
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
    // 시안 States-*: 회색 바탕 상자(선 line-2) · 경고 아이콘 + 문장 13 · '다시 시도'(테두리 알약 30) · '자세히'
    <div role="alert" className="flex flex-col gap-2.5 border border-line-2 bg-surface-2 p-3.5 text-[13px] text-ink">
      <p className="flex items-center gap-1.5"><AlertTriangle className="size-3.5 shrink-0" />{message}</p>
      <div className="flex items-center gap-1.5">
        {onRetry && <Button variant="outline" size="sm" className="h-[30px] gap-1.5 text-[12.5px]" onClick={onRetry}><RefreshCw className="size-3.5" />다시 시도</Button>}
        {error != null && <Tooltip>
          <TooltipTrigger asChild><Button variant="ghost" size="sm" className="h-[30px] text-[12.5px] text-ink-2">자세히</Button></TooltipTrigger>
          <TooltipContent className="max-w-[320px] text-xs">{toApiError(error).message}</TooltipContent>
        </Tooltip>}
      </div>
    </div>
  )
}

/** 표 모양 스켈레톤 — 실제 줄 수만큼 */
export function RowsSkeleton({ rows = 6, head = true, className }: { rows?: number; head?: boolean
  /** 최종 본문 높이(상한 눈금 등)에 맞출 때 */
  className?: string }) {
  return (
    <div role="status" aria-label="데이터 불러오는 중" aria-busy="true" className={cn("space-y-2 overflow-hidden", className)}>
      {head && <Skeleton className="h-4 w-2/3" />}
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-6 w-full" />)}
    </div>
  )
}
