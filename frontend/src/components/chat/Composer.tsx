import { useRef, useState, type ReactNode } from "react"
import { AtSign, Plus, Quote, X } from "lucide-react"
import { toast } from "sonner"
import { track } from "@/lib/usage"
import { InfoTip } from "@/components/shared/InfoTip"
import { Button } from "@/components/ui/button"
import { Popover, PopoverAnchor } from "@/components/ui/popover"
import { Sheet } from "@/components/ui/sheet"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { targetValue } from "@/hooks/useChatTargets"
import { MOBILE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery"
import { addTarget, findAtQuery, MAX_TARGETS, removeAtQuery, sameTarget, sendable } from "@/lib/chatTargets"
import { cn } from "@/lib/utils"
import type { ChatTarget, ChatTargetKind } from "@/types"

import { TargetChip } from "./TargetChip"
import { TargetPopover, TargetSheetContent, type PickerHandle } from "./TargetPicker"
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
  /** 첨부 줄 맨 앞 — AI 패널의 '보고 있는 화면' 칩(PageChip) */
  attachments?: ReactNode
  /**
   * 붙인 대상 (ia-redesign §4.14a, D-311) — 주면 `@`·'＋'로 고르는 팝오버(폰은 시트)가 켜진다.
   * 대화 내내 남고 ×로 뺀다. 5개까지.
   */
  targets?: ChatTarget[]
  onTargetsChange?: (targets: ChatTarget[]) => void
}

type Picker = { mode: "at"; start: number; query: string } | { mode: "plus" }

/**
 * 컴포저 (시안 Chat · Chat-Tag) — 카드 한 장: [첨부 칩 줄] · 내용에 맞게 자라는 입력 · [＋ · @ · ⓘ · 상태 · 보내기].
 * Enter 전송 / Shift+Enter 줄바꿈. 정지 버튼은 없다(취소 API 부재, chat-page.md §7). 입력 아래 안내 줄은 두지 않고 ⓘ에 둔다.
 * `@` 입력 → 후보 팝오버(↑↓·Enter·Esc는 입력 칸이 받는다). 고르면 `@검색어`를 지우고 칩을 붙인다.
 */
export function Composer({ value, onChange, onSubmit, busy, placeholder, autoFocus, className, hint, quote, onClearQuote, textareaRef, attachments, targets, onTargetsChange }: Props) {
  const canSend = !busy && (value.trim().length > 0 || !!quote)
  const tagging = !!onTargetsChange
  const list = targets ?? []
  const phone = useMediaQuery(MOBILE_QUERY)
  const [picker, setPicker] = useState<Picker | null>(null)
  const [kind, setKind] = useState<ChatTargetKind | null>(null)
  const [plusQuery, setPlusQuery] = useState("")
  const inner = useRef<HTMLTextAreaElement | null>(null)
  const anchor = useRef<HTMLDivElement>(null)
  const pickerRef = useRef<PickerHandle>(null)
  const full = sendable(list).length >= MAX_TARGETS
  const query = picker?.mode === "at" ? picker.query : plusQuery

  const setRefs = (el: HTMLTextAreaElement | null) => {
    inner.current = el
    if (typeof textareaRef === "function") textareaRef(el)
    else if (textareaRef) (textareaRef as React.MutableRefObject<HTMLTextAreaElement | null>).current = el
  }
  const close = () => { setPicker(null); setKind(null); setPlusQuery("") }
  const focusInput = () => requestAnimationFrame(() => inner.current?.focus())

  const pick = (picked: ChatTarget[]) => {
    if (!onTargetsChange) return
    let next = list
    for (const t of picked) next = addTarget(next, t)
    if (next.length - list.length < picked.length && sendable(next).length >= MAX_TARGETS) toast.info(`대상은 한 번에 ${MAX_TARGETS}개까지 붙일 수 있습니다.`)
    onTargetsChange(next)
    if (picker?.mode === "at") onChange(removeAtQuery(value, picker))
    track("action", "chat.attach", { entity: picked.map(t => t.kind).join(",") })
    close()
    focusInput()
  }

  const onText = (text: string, caret: number) => {
    onChange(text)
    if (!tagging) return
    const at = findAtQuery(text, caret)
    if (at) { setPicker({ mode: "at", ...at }); return }
    if (picker?.mode === "at") close()
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (picker?.mode === "at" && !phone) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); pickerRef.current?.move(e.key === "ArrowDown" ? 1 : -1); return }
      if (e.key === "Enter" && !e.nativeEvent.isComposing && pickerRef.current?.enter()) { e.preventDefault(); return }
      if (e.key === "Escape") { e.preventDefault(); close(); return }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (canSend) track("action", "chat.ask"); onSubmit() }
  }

  /** '@' 버튼 — 커서 자리에 '@'를 넣고 팝오버를 연다 */
  const insertAt = () => {
    const el = inner.current
    const caret = el?.selectionStart ?? value.length
    const pre = value.slice(0, caret)
    const glue = pre && !/\s$/.test(pre) ? " @" : "@"
    const text = pre + glue + value.slice(caret)
    onText(text, caret + glue.length)
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(caret + glue.length, caret + glue.length) })
  }

  const chips = tagging && list.map(t => (
    <TargetChip key={targetValue(t)} target={t} onRemove={() => onTargetsChange!(list.filter(x => !sameTarget(x, t)))} />
  ))
  const hasRow = !!attachments || list.length > 0

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
      <Popover open={tagging && !!picker && !phone} onOpenChange={open => { if (!open) close() }}>
        <PopoverAnchor asChild>
          <div ref={anchor} data-composer className="flex flex-col gap-2 rounded-2xl border bg-card px-3.5 py-3 transition-colors focus-within:border-ring">
            {hasRow && <div data-composer-attachments className="flex flex-wrap items-center gap-1.5">{attachments}{chips}</div>}
            <Textarea
              ref={setRefs}
              value={value}
              autoFocus={autoFocus}
              onChange={(e) => onText(e.target.value, e.target.selectionStart ?? e.target.value.length)}
              onKeyDown={onKeyDown}
              placeholder={placeholder}
              rows={1}
              aria-label="질문 입력"
              aria-expanded={tagging ? !!picker : undefined}
              className="min-h-10 max-h-48 flex-1 rounded-none border-0 bg-transparent px-0 py-1 text-[15px] leading-6 shadow-none focus-visible:border-transparent focus-visible:ring-0 dark:bg-transparent md:text-[15px]"
            />
            <div className="flex items-center gap-1.5">
              {tagging && <>
                <Button variant="outline" size="icon-sm" className="rounded-full max-md:size-10" aria-label="대상 붙이기"
                  onClick={() => { if (picker?.mode === "plus") close(); else { setPicker({ mode: "plus" }); setKind(null) } }}>
                  <Plus className="size-4" />
                </Button>
                <Button variant="ghost" size="icon-sm" className="text-muted-foreground max-md:size-10" aria-label="@로 대상 찾기" onClick={insertAt}>
                  <AtSign className="size-3.5" />
                </Button>
              </>}
              <span className="max-md:hidden"><InfoTip label="답변 기준">근거는 수집 자료·공시·시세입니다. 근거 밖 내용은 답하지 않고, 매매 처방은 하지 않습니다.{tagging && " @나 ＋로 종목·서사·질문·자료를 붙이면 그 대상의 자료를 먼저 읽습니다."} Enter 전송 · Shift+Enter 줄바꿈.</InfoTip></span>
              {hint && <span className="min-w-0 truncate text-xs text-muted-foreground max-md:hidden">{hint}</span>}
              <Button size="sm" onClick={() => { track("action", "chat.ask"); onSubmit() }} disabled={!canSend}
                aria-label={busy ? "답변 생성 중" : "질문 보내기"} className="ml-auto shrink-0 rounded-full px-4 max-md:h-10">
                {busy ? <Spinner className="size-4" /> : "보내기"}
              </Button>
            </div>
          </div>
        </PopoverAnchor>
        {tagging && !phone && (
          <TargetPopover ref={pickerRef} open={!!picker} mode={picker?.mode ?? "at"} query={query} onQuery={setPlusQuery}
            kind={kind} onKind={setKind} onPick={t => pick([t])} attached={list} full={full} keepOpenWithin={anchor} />
        )}
      </Popover>
      {tagging && phone && (
        <Sheet open={!!picker} onOpenChange={open => { if (!open) close() }}>
          <TargetSheetContent initialQuery={picker?.mode === "at" ? picker.query : ""} attached={list} onConfirm={pick} />
        </Sheet>
      )}
    </div>
  )
}
