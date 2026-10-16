import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { formatRatio } from "@/utils/format"
import type { TradeFlag } from "@/types"

/** 수출입 판정 배지 — 서버 판정(trade_metrics.classify)을 그대로 보인다. none이면 아무것도 그리지 않는다 */
const FLAG: Record<Exclude<TradeFlag, "none">, { label: string; tone: string }> = {
  surge: { label: "급등", tone: "border-up/40 text-up" },
  plunge: { label: "급감", tone: "border-down/40 text-down" },
  new: { label: "신규", tone: "text-muted-foreground" },
}

export function TradeFlagBadge({ flag, reason, contribution, nestedIn, className }: {
  flag: TradeFlag | null | undefined
  reason?: string | null
  /** 0~1 기여도 — 툴팁에 함께 */
  contribution?: number | null
  /** 상위 품목 이름 — '합계에서 제외' 안내 */
  nestedIn?: string | null
  className?: string
}) {
  if (!flag || flag === "none") return null
  const f = FLAG[flag]
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className={cn("h-4 shrink-0 px-1 text-[10px]", f.tone, className)}>{f.label}</Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-60 text-xs">
        <p>{reason ?? f.label}</p>
        {contribution != null && <p>전체 수출 증감 기여 {formatRatio(contribution * 100)}</p>}
        {nestedIn && <p className="text-muted-foreground">{nestedIn}의 세목 — 합계·기여도 분모에서 제외</p>}
        {flag !== "new" && <p className="text-muted-foreground">기준: 이 품목의 과거 YoY 분포 대비 z ≥ 2, 규모 ≥ $10M</p>}
      </TooltipContent>
    </Tooltip>
  )
}
