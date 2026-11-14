import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { chipLine, chipTip, narrativeHref, RULE_LABEL } from "@/lib/narrativeLinks"
import type { TopicNarrative } from "@/types"

/**
 * Market Today 화두 아래 '내러티브 [AI ›] [반도체 ›] [+1]' 줄 (ia-redesign §9.2).
 * 연결이 없으면 줄 자체를 그리지 않는다. 칩 툴팁 = 규칙·겹친 출처 건수·서사 버전·갱신일, +N 툴팁 = 접힌 서사 이름.
 */
export function NarrativeChipLine({ items }: { items: TopicNarrative[] }) {
  if (items.length === 0) return null
  const { shown, rest } = chipLine(items)
  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex flex-wrap items-center gap-1.5 text-[11px]" data-narrative-chips>
        <span className="text-muted-foreground">내러티브</span>
        {shown.map((n) => {
          const [rule, ver] = chipTip(n)
          return (
            <Tooltip key={n.topic}>
              <TooltipTrigger asChild>
                <Badge asChild variant="outline" className="h-5 rounded-none px-1.5 text-[11px] font-normal">
                  <Link to={narrativeHref(n.topic)}>{n.topic} ›</Link>
                </Badge>
              </TooltipTrigger>
              <TooltipContent className="max-w-[260px] text-xs leading-relaxed"><p className="font-semibold">{rule}</p><p>{ver}</p></TooltipContent>
            </Tooltip>
          )
        })}
        {rest.length > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" tabIndex={0} className="h-5 rounded-none px-1.5 text-[11px] font-normal text-muted-foreground" aria-label={`접힌 내러티브 ${rest.length}개`}>+{rest.length}</Badge>
            </TooltipTrigger>
            <TooltipContent className="max-w-[260px] text-xs leading-relaxed">
              {rest.map((n) => <p key={n.topic}>{n.topic} · {RULE_LABEL[n.rule]} · 출처 {n.doc_overlap}건</p>)}
            </TooltipContent>
          </Tooltip>
        )}
      </div>
    </TooltipProvider>
  )
}
