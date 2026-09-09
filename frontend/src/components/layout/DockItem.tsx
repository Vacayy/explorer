import { forwardRef, type ComponentProps } from "react"
import { Link } from "react-router-dom"
import type { LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface Props extends Omit<ComponentProps<typeof Button>, "children"> {
  icon: LucideIcon
  label: string
  to?: string
  active?: boolean
  /** 우상단 숫자 배지 (9+ 상한). tone: primary=저장, hypothesis=승인 대기(기계 제안) */
  badge?: number
  badgeTone?: "primary" | "hypothesis"
  emphasis?: boolean
}

/**
 * 도크 아이템 — 아이콘 20 + 라벨 11(상시, iOS 탭바 관용구) · 활성=primary 틴트+하단 점 · 호버=절제된 확대(1.06).
 * Link(to)면 이동, 아니면 버튼. 배지는 macOS 도크 관용구(우상단 원형 숫자).
 */
export const DockItem = forwardRef<HTMLButtonElement, Props>(function DockItem(
  { icon: Icon, label, to, active, badge, badgeTone = "primary", emphasis, className, ...rest }, ref,
) {
  const content = (
    <>
      <Icon className="size-5" aria-hidden />
      <span className={cn("text-[10.5px] leading-none", emphasis && !active && "font-medium text-foreground")}>{label}</span>
      {badge != null && badge > 0 && (
        <span className={cn(
          "absolute right-1.5 top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none tabular-nums text-white",
          badgeTone === "hypothesis" ? "bg-hypothesis" : "bg-primary",
        )}>
          {badge > 9 ? "9+" : badge}
        </span>
      )}
      {active && <span aria-hidden className="absolute bottom-0.5 size-1 rounded-full bg-primary" />}
    </>
  )
  const cls = cn(
    "relative h-12 w-14 flex-col gap-1 rounded-xl px-1 font-normal transition-[transform,background-color,color] duration-150",
    "hover:scale-[1.06] motion-reduce:hover:scale-100",
    active ? "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary" : "text-muted-foreground hover:text-foreground",
    className,
  )
  return (
    <Button ref={ref} variant="ghost" className={cls} aria-current={active ? "page" : undefined}
      asChild={!!to} aria-label={rest["aria-label"] ?? label} {...rest}>
      {to ? <Link to={to}>{content}</Link> : content}
    </Button>
  )
})
