import { ChevronsRight, Maximize2, ShieldQuestion, Sparkles } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { ChatMessage } from "@/types"

type FollowUp = { kind: string; question: string }

/** 후속 질문 종류 — 답의 어느 방향으로 더 갈지 (D-145, 종합 META가 판단) */
const KIND: Record<string, { label: string; Icon: LucideIcon }> = {
  deepen: { label: "더 파고들기", Icon: Sparkles },
  expand: { label: "넓히기", Icon: Maximize2 },
  challenge: { label: "반박·검증", Icon: ShieldQuestion },
  next: { label: "다음", Icon: ChevronsRight },
}

/**
 * 앞 답에서 남은 후속 질문 — 제안 중 하나를 물으면 나머지를 새 답 아래로 이월한다.
 * 고른 것으로 보는 기준은 다음 질문이 그 문구를 포함하는가(인용이 앞에 붙어도 잡힘). 제안과
 * 무관한 질문을 하면 이월이 끊겨 낡은 제안이 쌓이지 않는다.
 */
export function carriedFollowUps(messages: ChatMessage[]): FollowUp[] {
  let pool: FollowUp[] = []
  for (let i = 0; i < messages.length - 1; i++) {
    const m = messages[i], next = messages[i + 1]
    if (m.role !== "assistant") continue
    const candidates = [...(m.route?.follow_ups ?? []), ...pool]
    const asked = next.role === "user" ? candidates.find(f => next.content.includes(f.question)) : undefined
    pool = asked ? candidates.filter(f => f !== asked) : []
  }
  return pool
}

function FollowUpList({ items, onPick }: { items: FollowUp[]; onPick: (q: string) => void }) {
  return (
    <div className="flex flex-wrap items-start gap-1.5">
      {items.map((f, i) => {
        const meta = KIND[f.kind] ?? KIND.next
        return (
          <Button key={i} variant="outline" onClick={() => onPick(f.question)} data-follow-up={f.kind}
            className="h-auto min-h-8 max-w-full justify-start gap-1.5 rounded-full px-3 py-1.5 text-left font-normal whitespace-normal max-md:min-h-10">
            <meta.Icon className="size-3.5 shrink-0 text-hypothesis" aria-hidden />
            <span className="min-w-0 text-[13px] leading-snug">{f.question}</span>
            <span className="sr-only">({meta.label})</span>
          </Button>
        )
      })}
    </div>
  )
}

/**
 * 후속 질문 제안 — 마지막 답변 아래 칩 줄(시안 Chat, docs/specs/chat-page.md §4). 앞 답에서 남은 것은 따로 이어 보인다.
 * 클릭은 **컴포저에 채우기**이지 바로 전송이 아니다 — 한 턴이 100초·실비라 오클릭을 막고,
 * 사용자가 문구를 다듬을 여지를 남긴다.
 */
export function FollowUps({ items, carried = [], onPick }: {
  items: FollowUp[]
  carried?: FollowUp[]
  onPick: (q: string) => void
}) {
  if (items.length === 0 && carried.length === 0) return null
  return (
    <div className="space-y-3 pt-1">
      {items.length > 0 && (
        <div className="space-y-1.5">
          <p className="sr-only">이어서 물어볼 것</p>
          <FollowUpList items={items} onPick={onPick} />
        </div>
      )}
      {carried.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">앞 답에서 남은 질문</p>
          <FollowUpList items={carried} onPick={onPick} />
        </div>
      )}
    </div>
  )
}
