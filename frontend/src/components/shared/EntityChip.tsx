import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { EntityTag } from "@/types"

/**
 * 문서에 태깅된 엔티티 칩. 클릭하면 해당 엔티티로 필터를 적용한다.
 * confidence가 낮은 태그(자동 키워드 매칭)는 흐리게 — epistemic 규율의 UI화.
 */
export function EntityChip({ tag, onFilter }: {
  tag: EntityTag
  onFilter?: (tag: EntityTag) => void
}) {
  const lowConfidence = (tag.confidence ?? 1) < 0.6
  return (
    <Badge
      variant={tag.link_type === "stock" ? "default" : "outline"}
      className={cn(
        "text-caption font-normal cursor-pointer select-none",
        tag.link_type === "stock" && "bg-primary/10 text-primary border-transparent hover:bg-primary/20",
        lowConfidence && "opacity-60",
      )}
      onClick={() => onFilter?.(tag)}
      title={lowConfidence ? "자동 태깅 (낮은 확신도)" : undefined}
    >
      {tag.name}
    </Badge>
  )
}
