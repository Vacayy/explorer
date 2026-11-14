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
      // 시안 Feed: 테마·주제 = 테두리 칩, 종목 = 채운 칩(회색)
      variant={tag.link_type === "stock" ? "neutral" : "outline"}
      className={cn("cursor-pointer select-none hover:text-ink", lowConfidence && "opacity-60")}
      onClick={() => onFilter?.(tag)}
      title={lowConfidence ? "자동 태깅 (낮은 확신도)" : undefined}
    >
      {tag.name}
    </Badge>
  )
}
