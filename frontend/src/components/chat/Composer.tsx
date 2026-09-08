import { ArrowUp } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

interface Props {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  /** 답변 생성 중 — 전송 잠금, 버튼은 스피너 */
  busy: boolean
  placeholder: string
  autoFocus?: boolean
  className?: string
  hint?: string
}

/**
 * 컴포저 — 내용에 맞게 자라는 입력(상한 후 스크롤) + 입력 안 우측 하단 전송 버튼.
 * Enter 전송 / Shift+Enter 줄바꿈. 정지 버튼은 없다(취소 API 부재, spec §7).
 */
export function Composer({ value, onChange, onSubmit, busy, placeholder, autoFocus, className, hint }: Props) {
  const canSend = !busy && value.trim().length > 0
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-end gap-2 rounded-2xl bg-card p-2 pl-4 ring-1 ring-border shadow-sm transition-shadow focus-within:ring-ring focus-within:shadow-md">
        <Textarea
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSubmit() }
          }}
          placeholder={placeholder}
          rows={1}
          aria-label="질문 입력"
          className="min-h-0 max-h-48 flex-1 rounded-none border-0 bg-transparent px-0 py-2 text-[15px] leading-6 shadow-none focus-visible:border-transparent focus-visible:ring-0 md:text-[15px]"
        />
        <Button size="icon" onClick={onSubmit} disabled={!canSend}
          aria-label={busy ? "답변 생성 중" : "질문 보내기"} className="shrink-0 rounded-xl">
          {busy ? <Spinner className="size-4" /> : <ArrowUp className="size-4" />}
        </Button>
      </div>
      <p className="px-1 text-center text-[11px] text-muted-foreground">
        {hint ?? "Enter 전송 · Shift+Enter 줄바꿈 · 답변은 AI 종합이며 근거 밖 내용은 답하지 않습니다"}
      </p>
    </div>
  )
}
