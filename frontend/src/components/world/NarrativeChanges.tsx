import { ArrowRight } from "lucide-react"
import { cn } from "@/lib/utils"
import type { WorldEdgeBrief } from "@/types"

/** 고리 하나 — '+ A → B'(새로 생김) / '− A → B'(사라짐). 화살표 색 = 효과 방향 */
export function EdgeChip({ e, kind }: { e: WorldEdgeBrief; kind: "added" | "removed" }) {
  return <span className={cn("inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px]",
    kind === "removed" && "text-muted-foreground line-through decoration-muted-foreground/50")}>
    <span aria-hidden="true" className={kind === "added" ? "text-primary" : "text-muted-foreground"}>{kind === "added" ? "+" : "−"}</span>
    <span className="truncate">{e.from}</span>
    <ArrowRight aria-hidden="true" className={cn("size-3 shrink-0", e.effect_direction === "positive" ? "text-up-ink" : e.effect_direction === "negative" ? "text-down-ink" : "text-muted-foreground")} />
    <span className="truncate">{e.to}</span>
  </span>
}
