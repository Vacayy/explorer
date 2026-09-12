import { ChevronsRight, Maximize2, ShieldQuestion, Sparkles } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"

/** 후속 질문 종류 — 답의 어느 방향으로 더 갈지 (D-145, 종합 META가 판단) */
const KIND: Record<string, { label: string; Icon: LucideIcon }> = {
  deepen: { label: "더 파고들기", Icon: Sparkles },
  expand: { label: "넓히기", Icon: Maximize2 },
  challenge: { label: "반박·검증", Icon: ShieldQuestion },
  next: { label: "다음", Icon: ChevronsRight },
}

/**
 * 후속 질문 제안 — 마지막 답변 아래에만 (docs/specs/chat-page.md §4).
 * 클릭은 **컴포저에 채우기**이지 바로 전송이 아니다 — 한 턴이 100초·실비라 오클릭을 막고,
 * 사용자가 문구를 다듬을 여지를 남긴다.
 */
export function FollowUps({ items, onPick }: {
  items: { kind: string; question: string }[]
  onPick: (q: string) => void
}) {
  if (items.length === 0) return null
  return (
    <div className="space-y-1.5 pt-1">
      <p className="text-xs font-medium text-muted-foreground">이어서 물어볼 것</p>
      <div className="flex flex-col items-start gap-1.5">
        {items.map((f, i) => {
          const meta = KIND[f.kind] ?? KIND.next
          return (
            <Button key={i} variant="outline" onClick={() => onPick(f.question)}
              className="h-auto max-w-full justify-start gap-2 rounded-xl px-3 py-2 text-left font-normal whitespace-normal">
              <meta.Icon className="mt-0.5 size-3.5 shrink-0 text-hypothesis" />
              <span className="min-w-0 text-[13px] leading-relaxed">{f.question}</span>
              <span className="shrink-0 text-[11px] text-muted-foreground">{meta.label}</span>
            </Button>
          )
        })}
      </div>
    </div>
  )
}
