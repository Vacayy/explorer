import type { ReactNode } from "react"
import { Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/** ⓘ 툴팁 — 화면에 부연설명을 쓰지 않고 꼭 필요한 설명만 여기에 둔다 (ia-redesign 공통 규칙) */
export function InfoTip({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return <Tooltip>
    <TooltipTrigger asChild>
      <Button variant="ghost" size="icon-xs" aria-label={label} className={cn("shrink-0 text-muted-foreground/70", className)}><Info className="size-3.5" /></Button>
    </TooltipTrigger>
    <TooltipContent className="max-w-[360px] text-xs font-normal leading-relaxed">{children}</TooltipContent>
  </Tooltip>
}

/** 번호 섹션 — 머리(번호 · 제목 · 읽는 법 ⓘ) + 본문 */
export function Section({ id, step, title, how, actions, children }: { id: string; step?: number | string; title: string; how?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return <Card id={id} className="scroll-mt-24">
    <CardHeader className="flex flex-row flex-wrap items-center gap-1.5 space-y-0">
      <CardTitle className="flex items-baseline gap-2">{step != null && <span className="tabular-nums">{step}</span>}{title}</CardTitle>
      {how && <InfoTip label={`${title} 읽는 법`}>{how}</InfoTip>}
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </CardHeader>
    <CardContent className="space-y-4">{children}</CardContent>
  </Card>
}
