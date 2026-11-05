import type { ReactNode } from "react"
import { Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

/** ⓘ 툴팁 — 화면에 부연설명 줄을 쓰지 않고 꼭 필요한 설명만 여기에 둔다 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-xs" aria-label={label} className="shrink-0 text-muted-foreground/70"><Info className="size-3.5" /></Button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[300px] text-xs leading-relaxed">{children}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
