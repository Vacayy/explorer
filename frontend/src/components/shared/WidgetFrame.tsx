import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { GripVertical, Maximize2, MoreHorizontal, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/**
 * 위젯 틀 — 머리 40px(손잡이·제목·원천 기준 시각·메뉴) + 본문 (docs/specs/home-widgets.md §2).
 * 손잡이(.widget-handle)만 끌 수 있다. 편집 중엔 메뉴 대신 삭제 버튼.
 */
export function WidgetFrame({ title, asOf, stale, detailPath, editing, onRemove, flat, children }: {
  title: string
  asOf?: string | null
  /** 원천이 묵었거나 일부 실패 — 기준 시각을 주의 색으로 */
  stale?: boolean
  detailPath?: string
  editing: boolean
  onRemove: () => void
  /** 띠형(높이 1) — 머리 없이 본문만, 편집 중엔 손잡이·삭제를 겹쳐 띄운다 */
  flat?: boolean
  children: ReactNode
}) {
  return (
    <Card className={cn("relative flex h-full min-h-0 flex-col gap-0 overflow-hidden rounded-xl py-0 shadow-none", editing && "outline-1 outline-dashed outline-border outline-offset-2")}>
      {flat && editing && (
        /* 띠형은 높이가 한 칸이라 편집 중에도 머리 대신 작은 도구만 겹쳐 띄운다 */
        <div className="absolute top-1 right-1 z-10 flex items-center gap-0.5 rounded-md border bg-background/95 px-1 shadow-sm">
          <span className="widget-handle cursor-grab p-0.5 text-muted-foreground active:cursor-grabbing" aria-label={`${title} 옮기기`}><GripVertical className="size-3.5" /></span>
          <Button variant="ghost" size="icon-xs" aria-label={`${title} 삭제`} onClick={onRemove}><X className="size-3.5" /></Button>
        </div>
      )}
      {!flat && (
        <header className="flex h-10 shrink-0 items-center gap-1.5 border-b pr-1.5 pl-3">
          {editing && <span className="widget-handle -ml-1 cursor-grab text-muted-foreground active:cursor-grabbing" aria-label={`${title} 옮기기`}><GripVertical className="size-4" /></span>}
          <h3 className="min-w-0 truncate text-sm font-semibold">{title}</h3>
          {asOf && <span className={cn("ml-auto shrink-0 font-mono text-[11px] tabular-nums", stale ? "text-chart-warning" : "text-muted-foreground")}>{asOf}</span>}
          {editing
            ? <Button variant="ghost" size="icon-xs" className={cn(!asOf && "ml-auto")} aria-label={`${title} 삭제`} onClick={onRemove}><X className="size-3.5" /></Button>
            : detailPath && <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-xs" className={cn(!asOf && "ml-auto")} aria-label={`${title} 메뉴`}><MoreHorizontal className="size-3.5" /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem asChild><Link to={detailPath}><Maximize2 /> 전체 보기</Link></DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>}
        </header>
      )}
      <div className={cn("min-h-0 flex-1 overflow-hidden", flat ? "px-1 py-2" : "p-3")}>{children}</div>
    </Card>
  )
}

/** 위젯 본문 공통 상태 — 로딩·오류·빈 상태 (5-state) */
export function WidgetState({ loading, error, empty, onRetry, emptyText = "표시할 데이터가 아직 없어요" }: {
  loading?: boolean; error?: boolean; empty?: boolean; onRetry?: () => void; emptyText?: string
}) {
  if (loading) return <div className="space-y-2"><Skeleton className="h-7 w-1/2" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div>
  if (error) return <div className="space-y-2 text-sm text-muted-foreground"><p>불러오지 못했어요.</p>{onRetry && <Button variant="outline" size="sm" onClick={onRetry}>다시 시도</Button>}</div>
  if (empty) return <p className="text-sm text-muted-foreground">{emptyText}</p>
  return null
}

/** 큰 숫자 + 보조 표시 */
export function WidgetHero({ value, aside, className }: { value: ReactNode; aside?: ReactNode; className?: string }) {
  return <div className={cn("flex flex-wrap items-baseline gap-x-2 gap-y-1", className)}>
    <span className="text-[26px] leading-tight font-semibold tracking-tight tabular-nums">{value}</span>
    {aside}
  </div>
}
