import type { ComponentType, SVGProps } from "react"
import { AppWindow, BookOpen, ChartNoAxesColumn, CircleHelp, FileText, Globe, Layers, Tag, Text, User, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { chipMeta, KIND_NAME } from "@/lib/chatTargets"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { AttachmentRef, ChatTarget, ChatTargetKind } from "@/types"

export const KIND_ICON: Record<ChatTargetKind, ComponentType<SVGProps<SVGSVGElement>>> = {
  stock: ChartNoAxesColumn, us_stock: Globe, narrative: Text, question: CircleHelp, doc: FileText,
  person: User, theme: Tag, peer_group: Layers, report: BookOpen,
}

const CHIP = "inline-flex max-w-full items-center gap-1 rounded-full border text-xs"

/** 칩 앞 글자 — 종목은 이름만, 질문은 '질문 #7', 그 외 '서사 · ' */
function head(t: AttachmentRef & { code?: string | null }) {
  if (t.kind === "stock" || t.kind === "us_stock") return null
  if (t.kind === "question") return `질문 ${t.code ?? `#${t.ref}`}`
  return `${KIND_NAME[t.kind]} ·`
}

/**
 * 붙인 대상 칩 (시안 Chat-Tag B) — 종류 아이콘 · 이름 · (종목 코드·등락 / 서사·자료 날짜 / 질문 번호) · ×.
 * 긴 이름은 말줄임, 전체 이름은 툴팁. 사라진 대상은 흐린 점선 칩(설명은 툴팁)으로 두고 보낼 때 뺀다.
 */
export function TargetChip({ target, onRemove, size = "md" }: { target: ChatTarget; onRemove?: () => void; size?: "md" | "sm" }) {
  const Icon = KIND_ICON[target.kind]
  const gone = target.available === false
  const meta = target.kind === "question" ? null : chipMeta(target)
  const change = target.kind === "stock" ? target.change_pct : null
  const label = target.label || target.ref
  return (
    <span data-target-chip={`${target.kind}:${target.ref}`} data-gone={gone || undefined}
      className={cn(CHIP, size === "sm" ? "h-6 bg-background px-2 text-[11px]" : "h-7 bg-card pl-2.5", size === "md" && (onRemove ? "pr-0.5" : "pr-2.5"),
        gone && "border-dashed opacity-60")}>
      <Icon className="size-3 shrink-0 text-muted-foreground" aria-hidden />
      {head(target) && <span className="shrink-0 text-muted-foreground">{head(target)}</span>}
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={cn("min-w-0 truncate", size === "sm" ? "max-w-[140px]" : "max-w-[180px]", gone && "line-through")}>{label}</span>
          </TooltipTrigger>
          <TooltipContent className="max-w-[320px] text-xs">{gone ? <>{label}<br />보관되거나 지워진 대상이라 보낼 때 빠집니다</> : label}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {meta && <span className="shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums">{meta}</span>}
      {change != null && size === "md" && <span className={cn("shrink-0 font-mono text-[11px] tabular-nums", change > 0 ? "text-up-ink" : change < 0 ? "text-down-ink" : "text-muted-foreground")}>{formatPercent(change)}</span>}
      {onRemove && (
        <Button variant="ghost" size="icon-xs" className="size-6 shrink-0 rounded-full" aria-label={`${label} 빼기`} onClick={onRemove}>
          <X className="size-3" />
        </Button>
      )}
    </span>
  )
}

/** '보고 있는 화면' 칩 — 자동으로 붙고, 붙인 대상 줄 맨 앞에 흐린 점선으로 둔다 */
export function PageChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span data-page-context className={cn(CHIP, "h-7 border-dashed bg-transparent pr-0.5 pl-2.5 text-muted-foreground")}>
      <AppWindow className="size-3 shrink-0" aria-hidden />
      <span className="truncate">보고 있는 화면 · {label}</span>
      <Button variant="ghost" size="icon-xs" className="size-6 shrink-0 rounded-full" aria-label="이번 질문에서 화면 맥락 빼기" onClick={onRemove}><X className="size-3" /></Button>
    </span>
  )
}
