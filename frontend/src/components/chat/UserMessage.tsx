import { Check, Copy, PencilLine } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function useCopy() {
  const [copied, setCopied] = useState(false)
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* 클립보드 권한 없음 — 조용히 무시 */ }
  }
  return { copied, copy }
}

/** 사용자 메시지 — 우측 정렬 옅은 배경. 호버 액션: 복사 · 다시 질문(컴포저 프리필) */
export function UserMessage({ content, pending, onReask }: { content: string; pending?: boolean; onReask?: (q: string) => void }) {
  const { copied, copy } = useCopy()
  return (
    <div className={cn("group/msg flex flex-col items-end gap-1", pending && "opacity-60")}>
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-muted px-4 py-2.5 text-[15px] leading-6">
        {content}
      </div>
      {!pending && (
        <div className="flex gap-0.5 opacity-0 transition-opacity group-hover/msg:opacity-100 focus-within:opacity-100 max-md:opacity-100">
          <Button variant="ghost" size="icon-xs" aria-label="복사" onClick={() => copy(content)}>
            {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          </Button>
          {onReask && (
            <Button variant="ghost" size="icon-xs" aria-label="다시 질문" onClick={() => onReask(content)}>
              <PencilLine className="size-3" />
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
