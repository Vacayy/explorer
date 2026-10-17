import type { KeyboardEvent, ReactNode } from "react"
import { Link } from "react-router-dom"
import { GripVertical, Maximize2, MoreHorizontal, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/**
 * 위젯 틀 — 머리 40px(손잡이·제목·원천 기준 시각·메뉴) + 본문 (docs/specs/home-widgets.md §2).
 * 손잡이(.widget-handle)만 끌 수 있다 — 본문의 링크·표를 누를 때 끌려가지 않게. 손잡이와 메뉴는 늘 있고 손잡이는 올렸을 때 진해진다.
 * 띠형(flat)은 머리 없이 본문만, 올렸을 때 손잡이·메뉴를 겹쳐 띄운다.
 */
export function WidgetFrame({ title, asOf, stale, detailPath, onRemove, onOpen, flat, children }: {
  title: string
  asOf?: string | null
  /** 원천이 묵었거나 일부 실패 — 기준 시각을 주의 색으로 */
  stale?: boolean
  detailPath?: string
  onRemove: () => void
  /** 본문을 누르면 상세 창 — 본문에 다른 링크가 없는 위젯만 */
  onOpen?: () => void
  flat?: boolean
  children: ReactNode
}) {
  const menu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-xs" aria-label={`${title} 메뉴`}><MoreHorizontal className="size-3.5" /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {detailPath && <DropdownMenuItem asChild><Link to={detailPath}><Maximize2 /> 전체 보기</Link></DropdownMenuItem>}
        <DropdownMenuItem onSelect={onRemove}><X /> 보드에서 빼기</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
  const handle = (
    <span className="widget-handle flex h-6 w-4 shrink-0 cursor-grab items-center justify-center rounded-sm text-muted-foreground/40 transition-colors group-hover/widget:text-muted-foreground hover:bg-muted active:cursor-grabbing"
      aria-label={`${title} 옮기기`} title="끌어서 옮기기"><GripVertical className="size-3.5" /></span>
  )
  return (
    <Card className="group/widget relative flex h-full min-h-0 flex-col gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none">
      {flat ? (
        <div className="absolute top-1 right-1 z-10 flex items-center gap-0.5 rounded-sm border bg-background/95 px-0.5 opacity-0 shadow-sm transition-opacity group-hover/widget:opacity-100 focus-within:opacity-100">
          {handle}{menu}
        </div>
      ) : (
        <header className="flex h-10 shrink-0 items-center gap-1 border-b pr-1.5 pl-1">
          {handle}
          <h3 className="min-w-0 truncate text-sm font-semibold">{title}</h3>
          {asOf && <span className={cn("ml-auto shrink-0 font-mono text-[11px] tabular-nums", stale ? "text-chart-warning" : "text-muted-foreground")}>{asOf}</span>}
          <span className={cn(!asOf && "ml-auto")}>{menu}</span>
        </header>
      )}
      <div className={cn("min-h-0 flex-1 overflow-hidden", flat ? "px-1 py-2" : "p-3", onOpen && "cursor-pointer transition-colors hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none")}
        {...(onOpen && { role: "button", tabIndex: 0, "aria-label": `${title} 자세히 보기`, onClick: onOpen,
          onKeyDown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen() } } })}>{children}</div>
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
