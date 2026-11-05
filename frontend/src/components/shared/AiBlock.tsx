import type { ReactNode } from "react"
import { Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"

interface Props {
  /** 라벨 — 기본 'AI 해석' */
  label?: ReactNode
  /** 라벨 옆 출처·생성 시각 (예: 'sonnet · 11/1') */
  meta?: ReactNode
  children: ReactNode
  className?: string
}

/**
 * AI 해석 블록 (DS-Components shared/AiBlock, D-320) — LLM이 만든 문장.
 * 보라 라벨 행 + 옅은 보라 틴트. 좌측 보더 강조는 쓰지 않는다. 사실 확인은 초록(--fact)으로 따로.
 */
export function AiBlock({ label = "AI 해석", meta, children, className }: Props) {
  return (
    <div data-slot="ai-block" className={cn("flex flex-col gap-2 bg-hyp-tint px-4 py-3.5", className)}>
      <div className="flex items-center gap-1.5 text-xs font-medium text-hyp">
        <Sparkles className="size-3" aria-hidden />{label}
        {meta && <span className="font-normal text-ink-3">· {meta}</span>}
      </div>
      <div className="text-sm leading-[1.65] text-pretty text-ink">{children}</div>
    </div>
  )
}
