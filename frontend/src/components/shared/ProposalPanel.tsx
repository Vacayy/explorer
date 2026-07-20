import type { ReactNode, ComponentType } from "react"
import { cn } from "@/lib/utils"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"

/**
 * 제안·승인 대기류 공통 카드 셸 — 내러티브 카드처럼 좌측 border 없는 단순 디자인.
 * 크기는 window 대비 비율(vh/vw)로 제한 → 반응형. 내부 컨텐츠가 넘치면 body(헤더 제외)만 스크롤.
 * 스크롤 핵심: max-height를 실제 스크롤 컨테이너인 ScrollArea viewport에 직접 건다
 * (Card·Root에만 걸면 viewport의 h-full이 확정 높이를 못 받아 스크롤이 안 잡힌다).
 */
interface ProposalPanelProps {
  title: ReactNode
  subtitle?: ReactNode
  icon?: ComponentType<{ className?: string }>
  count?: number
  action?: ReactNode              // 헤더 우측 슬롯 (링크 등)
  maxHeight?: string              // window 대비 비율 (기본 70vh) — viewport에 적용
  maxWidth?: string               // window 대비 비율 (기본 90vw) — Card에 적용
  className?: string
  contentClassName?: string
  children: ReactNode
}

export function ProposalPanel({
  title, subtitle, icon: Icon, count, action,
  maxHeight = "70vh", maxWidth = "90vw",
  className, contentClassName, children,
}: ProposalPanelProps) {
  return (
    <Card className={cn("w-full", className)} style={{ maxWidth }}>
      <CardHeader className="pb-2 flex items-center gap-2">
        {Icon && <Icon className="h-4 w-4 text-muted-foreground shrink-0" />}
        <CardTitle className="text-sm">{title}</CardTitle>
        {count != null && <Badge variant="secondary" className="text-[10px]">{count}</Badge>}
        {subtitle && <span className="text-[11px] text-muted-foreground">{subtitle}</span>}
        {action && <span className="ml-auto shrink-0">{action}</span>}
      </CardHeader>
      <ScrollArea viewportStyle={{ maxHeight }}>
        <CardContent className={contentClassName}>{children}</CardContent>
      </ScrollArea>
    </Card>
  )
}
