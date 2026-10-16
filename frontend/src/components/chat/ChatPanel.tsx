import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { History, Maximize2, SquarePen, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { useChat } from "@/hooks/useChat"
import { usePageContext } from "@/hooks/usePageContext"
import { PREF, readPref, setPanelThread, writePref } from "@/lib/shellPrefs"
import { AssistantMessage, StreamingMessage } from "./AssistantMessage"
import type { Quote as QuoteRef } from "./useQuoteSelection"
import { Composer } from "./Composer"
import { ThreadRail } from "./ThreadRail"
import { UserMessage } from "./UserMessage"

const BOTTOM_PX = 80
const SUGGESTIONS = ["오늘 시장 세 줄로 요약해줘", "이번 주 바뀐 서사 중 내 종목과 관련된 건?", "지금 보는 화면에서 놓치기 쉬운 점은?"]

/**
 * AI 대화 패널 — 오른쪽 360px, /chat 부품 재사용 (docs/specs/app-shell.md §5).
 * 보고 있는 화면을 page_context로 함께 보낸다(칩 ×로 이번 질문에서 뺄 수 있음). 활성 스레드는 localStorage.
 */
export function ChatPanel({ companyName, onClose, inputRef }: {
  companyName?: string | null
  onClose: () => void
  inputRef?: React.RefObject<HTMLTextAreaElement | null>
}) {
  const [activeId, setActiveId] = useState<number | null>(() => {
    const v = Number(readPref(PREF.thread))
    return Number.isFinite(v) && v > 0 ? v : null
  })
  const [question, setQuestion] = useState("")
  const [quote, setQuote] = useState<QuoteRef | null>(null)
  const [withPage, setWithPage] = useState(true)
  const [listOpen, setListOpen] = useState(false)
  const page = usePageContext(companyName)

  const openThread = useCallback((id: number) => {
    setActiveId(id); writePref(PREF.thread, String(id)); setListOpen(false)
  }, [])
  const newThread = () => { setActiveId(null); writePref(PREF.thread, null); setQuestion(""); setQuote(null); setListOpen(false) }
  useEffect(() => { setPanelThread(activeId); return () => setPanelThread(null) }, [activeId])
  useEffect(() => { setWithPage(true) }, [page?.path])    // 화면이 바뀌면 다시 붙인다

  const chat = useChat(activeId, openThread)
  const { detail, messages, awaiting, stalled, draft, ask } = chat
  const busy = ask.isPending || awaiting

  const submit = (text?: string) => {
    const q = (text ?? question).trim()
    if ((!q && !quote) || busy) return
    ask.mutate(
      { question: q || "이 대목을 더 자세히 설명해줘", conversation_id: activeId ?? undefined, quote: quote ?? undefined,
        page_context: withPage && page ? page : undefined },
      { onSuccess: () => { setQuestion(""); setQuote(null) } },
    )
    stickRef.current = true
  }

  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const onScroll = () => {
    const el = scrollRef.current
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_PX
  }
  useLayoutEffect(() => { const el = scrollRef.current; if (el) el.scrollTop = el.scrollHeight }, [activeId])
  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [messages.length, ask.isPending, awaiting, draft?.text.length])

  const thread = detail.data
  return (
    <aside aria-label="AI 대화"
      className="sticky top-(--topbar-height) flex h-[calc(100dvh-var(--topbar-height))] w-(--ai-panel-width) shrink-0 flex-col border-l bg-sidebar text-sidebar-foreground">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-3">
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{thread?.title || "AI 대화"}</h2>
        <Popover open={listOpen} onOpenChange={setListOpen}>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="대화 목록"><History className="size-4" /></Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="h-[min(520px,70dvh)] w-[300px] p-0">
            <ThreadRail threads={chat.threads} loading={chat.threadsLoading} error={chat.threadsError}
              activeId={activeId} onSelect={openThread} onNew={newThread} />
          </PopoverContent>
        </Popover>
        <Button variant="ghost" size="icon-sm" aria-label="새 대화" onClick={newThread}><SquarePen className="size-4" /></Button>
        <Button variant="ghost" size="icon-sm" aria-label="전체 화면으로 보기" asChild>
          <Link to={activeId ? `/chat?id=${activeId}` : "/chat"}><Maximize2 className="size-4" /></Link>
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="AI 대화 닫기 (⌘J)" onClick={onClose}><X className="size-4" /></Button>
      </header>

      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto px-4 py-3 text-[14px] [&_.prose]:text-[14px]">
        {!activeId && !ask.isPending ? (
          <div className="space-y-3 pt-2">
            <p className="text-sm text-muted-foreground">지금 보는 화면을 맥락으로 함께 보냅니다. 수집 문서·그래프·시세를 근거로 답합니다.</p>
            <div className="flex flex-col items-start gap-1.5">
              {SUGGESTIONS.map(s => (
                <Button key={s} variant="outline" size="sm" className="h-auto whitespace-normal py-1.5 text-left font-normal" onClick={() => submit(s)}>{s}</Button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {detail.isLoading && <><Skeleton className="ml-auto h-9 w-2/3 rounded-2xl" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></>}
            {detail.isError && <ErrorState message="대화를 불러올 수 없습니다." onRetry={() => detail.refetch()} />}
            {messages.map((m, i) => m.role === "user"
              ? <UserMessage key={m.id} content={m.content} onReask={setQuestion} />
              : <AssistantMessage key={m.id} m={m} isLast={i === messages.length - 1} onQuote={setQuote} onPick={setQuestion} />)}
            {ask.isPending && <UserMessage content={ask.variables?.question ?? ""} pending />}
            {(awaiting || ask.isPending) && <StreamingMessage draft={draft} />}
            {stalled && <p className="rounded-xl border border-destructive/30 px-3 py-2 text-[13px] text-destructive">답변 생성이 멈춘 것 같습니다 (5분 초과). 다시 질문해 주세요.</p>}
          </div>
        )}
      </div>

      <div className="shrink-0 space-y-1.5 border-t p-3">
        {page && withPage && (
          <span className="inline-flex max-w-full items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-xs text-muted-foreground">
            <span className="truncate">보는 화면: {page.label}</span>
            <button type="button" aria-label="이번 질문에서 화면 맥락 빼기" onClick={() => setWithPage(false)}
              className="shrink-0 rounded-full p-0.5 hover:bg-muted"><X className="size-3" /></button>
          </span>
        )}
        {ask.isError && <p className="text-xs text-destructive">질문을 보내지 못했습니다. 입력은 그대로 있으니 다시 시도해 주세요.</p>}
        <Composer value={question} onChange={setQuestion} onSubmit={() => submit()} busy={busy} textareaRef={inputRef}
          placeholder={activeId ? "이어서 질문…" : "지금 화면에 대해 물어보세요"} quote={quote} onClearQuote={() => setQuote(null)}
          hint={awaiting ? "답변을 생성하는 동안에는 이어서 질문할 수 없습니다" : undefined} />
      </div>
    </aside>
  )
}
