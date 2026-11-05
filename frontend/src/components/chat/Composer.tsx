import type { ReactNode } from "react"
import { Quote, X } from "lucide-react"
import { track } from "@/lib/usage"
import { InfoTip } from "@/components/shared/InfoTip"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

import type { Quote as QuoteRef } from "./useQuoteSelection"

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
  /** 드래그로 지목한 답변 대목 — 입력 위 칩으로 붙는다 (D-146) */
  quote?: QuoteRef | null
  onClearQuote?: () => void
  /** AI 패널이 ⌘J로 열릴 때 포커스 */
  textareaRef?: React.Ref<HTMLTextAreaElement>
  /**
   * 입력 카드 맨 위 칩 줄 — 질문과 함께 보낼 대상. 지금은 AI 패널의 '보고 있는 화면' 칩만 들어온다.
   * 종목·객체 태그(D-306, 별도 기획)가 생기면 같은 줄에 칩을 더한다. 비어 있으면 줄을 그리지 않는다.
   */
  attachments?: ReactNode
}

/**
 * 컴포저 (시안 Chat, ia-redesign §4.14) — 카드 한 장: [첨부 칩 줄] · 내용에 맞게 자라는 입력 · [ⓘ · 상태 · 보내기].
 * Enter 전송 / Shift+Enter 줄바꿈. 정지 버튼은 없다(취소 API 부재, chat-page.md §7). 입력 아래 안내 줄은 두지 않고 ⓘ에 둔다.
 */
export function Composer({ value, onChange, onSubmit, busy, placeholder, autoFocus, className, hint, quote, onClearQuote, textareaRef, attachments }: Props) {
  const canSend = !busy && (value.trim().length > 0 || !!quote)
  return (
    <div className={cn("space-y-1.5", className)}>
      {quote && (
        <div className="flex items-start gap-2 rounded-xl border border-hypothesis/30 bg-[color-mix(in_srgb,var(--hypothesis)_6%,var(--card))] px-3 py-2">
          <Quote className="mt-0.5 size-3.5 shrink-0 text-hypothesis" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[11px] text-muted-foreground">{quote.doc_id ? `문서 「${quote.doc_title || `#${quote.doc_id}`}」에서 지목한 대목` : "답변에서 지목한 대목"}{quote.citations.length > 0 && ` · 근거 ${quote.citations.length}건 함께 전달`}</p>
            <p className="line-clamp-2 text-[13px] leading-snug">{quote.selected}</p>
          </div>
          <Button variant="ghost" size="icon-xs" aria-label="인용 빼기" onClick={onClearQuote}>
            <X className="size-3" />
          </Button>
        </div>
      )}
      <div data-composer className="flex flex-col gap-2 rounded-2xl border bg-card px-3.5 py-3 transition-colors focus-within:border-ring">
        {attachments && <div data-composer-attachments className="flex flex-wrap items-center gap-1.5">{attachments}</div>}
        {/* 폰: 입력 · 보내기 한 줄(아래 줄을 contents로 풀어 같은 줄에 둔다), 데스크톱: 입력 아래 ⓘ · 상태 · 보내기 줄 */}
        <div className="flex items-end gap-2 md:flex-col md:items-stretch">
        <Textarea
          ref={textareaRef}
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (canSend) track("action", "chat.ask"); onSubmit() }
          }}
          placeholder={placeholder}
          rows={1}
          aria-label="질문 입력"
          className="min-h-10 max-h-48 flex-1 rounded-none border-0 bg-transparent px-0 py-1 text-[15px] leading-6 shadow-none focus-visible:border-transparent focus-visible:ring-0 dark:bg-transparent md:text-[15px]"
        />
        <div className="flex items-center gap-2 max-md:contents">
          <span className="max-md:hidden"><InfoTip label="답변 기준">근거는 수집 자료·공시·시세입니다. 근거 밖 내용은 답하지 않고, 매매 처방은 하지 않습니다.<span className="max-md:hidden"> Enter 전송 · Shift+Enter 줄바꿈.</span></InfoTip></span>
          {hint && <span className="min-w-0 truncate text-xs text-muted-foreground max-md:hidden">{hint}</span>}
          <Button size="sm" onClick={() => { track("action", "chat.ask"); onSubmit() }} disabled={!canSend}
            aria-label={busy ? "답변 생성 중" : "질문 보내기"} className="ml-auto shrink-0 rounded-full px-4 max-md:h-10">
            {busy ? <Spinner className="size-4" /> : "보내기"}
          </Button>
        </div>
        </div>
      </div>
    </div>
  )
}
