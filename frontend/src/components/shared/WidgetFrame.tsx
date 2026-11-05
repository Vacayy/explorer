import { toApiError } from "@/api/errors"
import type { ReactNode } from "react"
import { RotateCw, TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/* 위젯 본문 공통 조각 — 홈 고정 탭 섹션(home/HomeSection)이 위젯 본문을 그대로 쓴다. 옛 위젯 틀(끌기·빼기 메뉴)은 개편 3단계에서 제거 */

/** 위젯 본문 공통 상태 — 로딩·오류·빈 상태 (5-state) */
export function WidgetState({ loading, error, empty, onRetry, emptyText = "표시할 데이터가 아직 없어요" }: {
  loading?: boolean; error?: unknown; empty?: boolean; onRetry?: () => void; emptyText?: string
}) {
  if (loading) return <div role="status" aria-label="데이터 불러오는 중" aria-busy="true" className="space-y-2"><Skeleton className="h-7 w-1/2" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div>
  if (error) return <div role="alert" className="flex flex-col items-start gap-2.5 text-[12.5px] text-ink-2"><p className="flex items-center gap-1.5"><TriangleAlert className="size-3.5 shrink-0" aria-hidden />{error === true ? "불러오지 못했어요." : toApiError(error).message}</p>{onRetry && <Button variant="outline" size="sm" onClick={onRetry}><RotateCw className="size-3.5" aria-hidden />다시 시도</Button>}</div>
  if (empty) return <p role="status" className="text-[12.5px] text-ink-2">{emptyText}</p>
  return null
}

/** 큰 숫자 + 보조 표시 */
export function WidgetHero({ value, aside, className }: { value: ReactNode; aside?: ReactNode; className?: string }) {
  return <div className={cn("flex flex-wrap items-baseline gap-x-2 gap-y-1", className)}>
    <span className="font-mono text-[20px] leading-tight font-normal tabular-nums">{value}</span>
    {aside}
  </div>
}
