import { useLayoutEffect, useRef, useState } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

/**
 * 스캔 표면 원칙 (종목 홈): 접힌 상태에서 요지만, 전문은 1뎁스 펼침.
 * 내용이 collapsedHeight보다 짧으면 토글 없이 그대로 렌더.
 */
export function Expandable({ collapsedHeight = 260, className, children }: {
  collapsedHeight?: number
  className?: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (el) setOverflowing(el.scrollHeight > collapsedHeight + 24)
  }, [collapsedHeight, children])

  return (
    <div className={className}>
      <div
        ref={ref}
        className="relative overflow-hidden transition-[max-height]"
        style={{ maxHeight: open || !overflowing ? undefined : collapsedHeight }}
      >
        {children}
        {!open && overflowing && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-card to-transparent" />
        )}
      </div>
      {overflowing && (
        <button
          onClick={() => setOpen(!open)}
          className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
        >
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
          {open ? "접기" : "전체 보기"}
        </button>
      )}
    </div>
  )
}
