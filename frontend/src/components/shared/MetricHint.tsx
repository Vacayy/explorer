import type { ReactNode } from "react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

/** 계산값 근거 툴팁 — 모든 파생 지표는 hover로 '무엇으로 계산했나'를 밝힌다. */
export function MetricHint({ hint, children }: { hint: string; children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help">{children}</span>
        </TooltipTrigger>
        <TooltipContent className="max-w-[300px] text-xs leading-relaxed whitespace-pre-line">{hint}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
