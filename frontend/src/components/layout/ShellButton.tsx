import { forwardRef, type ComponentProps } from "react"
import type { LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

interface Props extends Omit<ComponentProps<typeof Button>, "children"> {
  icon: LucideIcon
  label: string
  /** 우상단 숫자 배지 (99+ 상한). tone: primary=저장, hypothesis=승인 대기(기계 제안) */
  badge?: number
  badgeTone?: "primary" | "hypothesis"
  /** 숫자 대신 작은 점(시안 Shell-Topbar 인박스) */
  dot?: boolean
  pressed?: boolean
}

/** 상단 바 아이콘 버튼 — 툴팁 라벨 + 선택 배지 (docs/specs/app-shell.md §3) */
export const ShellButton = forwardRef<HTMLButtonElement, Props>(function ShellButton(
  { icon: Icon, label, badge, badgeTone = "primary", dot, pressed, className, ...rest }, ref,
) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button ref={ref} variant="ghost" size="icon-sm" aria-label={rest["aria-label"] ?? label}
          aria-pressed={pressed} className={cn("relative rounded-lg text-ink-2 hover:bg-chip hover:text-ink max-md:size-10", pressed && "bg-chip text-ink", className)} {...rest}>
          <Icon className="size-[17px] max-md:size-[18px]" strokeWidth={1.7} aria-hidden />
          {dot && <span aria-hidden className="absolute right-1.5 top-1.5 size-[7px] rounded-full bg-hyp ring-2 ring-background" />}
          {badge != null && badge > 0 && (
            <span className={cn(
              "absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none tabular-nums",
              badgeTone === "hypothesis" ? "bg-hyp text-action-ink" : "bg-primary text-primary-foreground",
            )}>
              {badge > 99 ? "99+" : badge}
            </span>
          )}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
})
