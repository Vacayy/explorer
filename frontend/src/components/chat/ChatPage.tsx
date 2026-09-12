import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ArrowDown, PanelLeft, Send, SquarePen } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { useChat } from "@/hooks/useChat"
import { cn } from "@/lib/utils"
import { AssistantMessage, StreamingMessage } from "./AssistantMessage"
import type { Quote as QuoteRef } from "./useQuoteSelection"
import { ChatEmpty } from "./ChatEmpty"
import { Composer } from "./Composer"
import { ThreadRail } from "./ThreadRail"
import { UserMessage } from "./UserMessage"
import { ThreadTitle } from "./ThreadTitle"

/** 스크롤 컨테이너 하단에서 이 거리 이내면 "바닥" — 자동 스크롤 허용 */
const BOTTOM_PX = 80

/**
 * /chat — 대화 (P2-2, product-v3.md §2). 세 번째 프리미티브: 판단 인터페이스.
 * 화면 스펙: docs/specs/chat-page.md (D-135) — 좌측 스레드 레일(접힘·모바일 Sheet) + 중앙 768px 읽기 컬럼 + 하단 고정 컴포저.
 * URL ?id= 가 활성 스레드의 단일 상태 소스, ?q= 는 옴니바 프리필. 데이터·진행 규약은 hooks/useChat.ts.
 */
export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeId = searchParams.get("id") ? Number(searchParams.get("id")) : null
  const [question, setQuestion] = useState(searchParams.get("q") ?? "")
  const [quote, setQuote] = useState<QuoteRef | null>(null)
  const [railOpen, setRailOpen] = useState(true)
  const [sheetOpen, setSheetOpen] = useState(false)

  const openThread = useCallback((id: number) => {
    setSearchParams({ id: String(id) })
    setSheetOpen(false)
  }, [setSearchParams])
  const newThread = () => { setSearchParams({}); setQuestion(""); setQuote(null); setSheetOpen(false) }

  const chat = useChat(activeId, openThread)
  const { detail, messages, awaiting, stalled, draft, ask } = chat
  const busy = ask.isPending || awaiting

  const submit = () => {
    const q = question.trim()
    // 인용만 붙이고 전송해도 된다 — "이 대목 더 설명해줘"가 기본 의도
    if ((!q && !quote) || busy) return
    ask.mutate(
      { question: q || "이 대목을 더 자세히 설명해줘", conversation_id: activeId ?? undefined, quote: quote ?? undefined },
      { onSuccess: () => { setQuestion(""); setQuote(null) } },
    )
    stickRef.current = true
  }

  // ── 스크롤 규칙: 바닥일 때만 따라간다. 위로 올라가 읽는 중이면 끌어내리지 않고 "최신으로" 버튼을 보인다.
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const [atBottom, setAtBottom] = useState(true)
  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_PX
    stickRef.current = near
    setAtBottom(near)
  }
  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior })
    stickRef.current = true
  }
  useLayoutEffect(() => { scrollToBottom("instant") }, [activeId])   // 스레드 전환 = 무조건 바닥
  useEffect(() => {
    if (stickRef.current) scrollToBottom()
  }, [messages.length, ask.isPending, awaiting, draft?.text.length])

  const thread = detail.data
  const composerPlaceholder = activeId ? "이어서 질문… (이전 문답이 맥락으로 전달됩니다)" : "무엇이든 물어보세요"

  return (
    <div className="flex h-[calc(100dvh-var(--shell-offset))] gap-4">
      {/* 스레드 레일 — lg 이상 인라인(접힘 가능) */}
      <aside className={cn(
        "hidden shrink-0 overflow-hidden rounded-xl bg-sidebar text-sidebar-foreground transition-[width] duration-200 lg:block",
        railOpen ? "w-[260px]" : "w-0",
      )}>
        <div className="w-[260px] h-full">
          <ThreadRail threads={chat.threads} loading={chat.threadsLoading} error={chat.threadsError}
            activeId={activeId} onSelect={openThread} onNew={newThread} />
        </div>
      </aside>
      {/* 모바일·태블릿 — Sheet */}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="left" className="w-[300px] p-0 sm:max-w-[300px]">
          <SheetTitle className="sr-only">대화 목록</SheetTitle>
          <ThreadRail threads={chat.threads} loading={chat.threadsLoading} error={chat.threadsError}
            activeId={activeId} onSelect={openThread} onNew={newThread} />
        </SheetContent>
      </Sheet>

      {/* 중앙 */}
      <section className="flex min-w-0 flex-1 flex-col">
        {/* 헤더 — 슬림 1줄 */}
        <header className="flex h-9 items-center gap-2">
          <Button variant="ghost" size="icon-sm" aria-label="대화 목록" className="lg:hidden" onClick={() => setSheetOpen(true)}>
            <PanelLeft className="size-4" />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label={railOpen ? "목록 접기" : "목록 펼치기"} className="hidden lg:inline-flex"
            onClick={() => setRailOpen((v) => !v)}>
            <PanelLeft className="size-4" />
          </Button>
          {thread && (
            <>
              <ThreadTitle id={thread.id} title={thread.title} />
              {thread.study_project && <Button variant="outline" size="sm" asChild><Link to={`/study/projects/${thread.study_project.id}`}>프로젝트에서 계속 공부하기</Link></Button>}
              {thread.study && <Button variant="outline" size="sm" asChild><Link to={`/study/${thread.study.id}`}>문서에서 계속 공부하기</Link></Button>}
              {thread.channel === "telegram" && (
                <Badge variant="outline" className="shrink-0 gap-1 text-[10px] font-normal"><Send className="size-2.5" /> 텔레그램</Badge>
              )}
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{messages.length}개</span>
              <Button variant="ghost" size="icon-sm" aria-label="새 대화" className="ml-auto lg:hidden" onClick={newThread}>
                <SquarePen className="size-4" />
              </Button>
            </>
          )}
        </header>

        {!!thread?.attached_documents?.length && <Collapsible className="my-2 rounded-xl border px-3 py-2">
          <CollapsibleTrigger asChild><Button size="sm" variant="ghost">함께 읽는 수집 자료 {thread.attached_documents.length}개</Button></CollapsibleTrigger>
          <CollapsibleContent className="space-y-2 pb-2">
            <p className="text-xs text-muted-foreground">이 대화의 후속 질문에서도 참고합니다. 다른 주제는 새 대화로 시작할 수 있습니다.</p>
            {thread.attached_documents.map(doc => <Link className="block text-sm text-primary hover:underline" key={doc.id} to={`/experiments/expectations?read=${doc.id}`}>{doc.title || '수집 자료'}</Link>)}
            <Button size="sm" variant="outline" onClick={newThread}>첨부 없이 새 대화</Button>
          </CollapsibleContent>
        </Collapsible>}
        {!activeId && !ask.isPending ? (
          /* Empty — 인사 + 중앙 컴포저 + 제안 카드 */
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ChatEmpty onPick={setQuestion}>
              <Composer value={question} onChange={setQuestion} onSubmit={submit} busy={busy}
                placeholder={composerPlaceholder} autoFocus quote={quote} onClearQuote={() => setQuote(null)} />
              {ask.isError && <p className="pt-2 text-center text-xs text-destructive">질문을 보내지 못했습니다. 다시 시도해주세요.</p>}
            </ChatEmpty>
          </div>
        ) : (
          <>
            {/* 메시지 스트림 */}
            <div ref={scrollRef} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-[768px] space-y-8 px-1 pt-3 pb-6">
                {detail.isLoading && (
                  <>
                    <Skeleton className="ml-auto h-11 w-1/2 rounded-2xl" />
                    <div className="space-y-2.5">
                      <Skeleton className="h-3.5 w-32" />
                      <Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-3/4" />
                    </div>
                  </>
                )}
                {detail.isError && (
                  <ErrorState message="대화를 불러올 수 없습니다." onRetry={() => detail.refetch()} />
                )}
                {messages.map((m, i) =>
                  m.role === "user"
                    ? <UserMessage key={m.id} content={m.content} onReask={setQuestion} />
                    : <AssistantMessage key={m.id} m={m} isLast={i === messages.length - 1}
                        onQuote={setQuote} onPick={setQuestion} />
                )}
                {/* 제출 직후 찰나(서버 적재 전) — 낙관적 표시 */}
                {ask.isPending && <UserMessage content={ask.variables?.question ?? ""} pending />}
                {(awaiting || ask.isPending) && <StreamingMessage draft={draft} />}
                {stalled && (
                  <p className="rounded-xl border border-destructive/30 px-4 py-3 text-[13px] text-destructive">
                    답변 생성이 멈춘 것 같습니다 (5분 초과). 서버 상태를 확인하고 다시 질문해주세요.
                  </p>
                )}
              </div>
            </div>

            {/* 컴포저 — 하단 고정 */}
            <div className="relative mx-auto w-full max-w-[768px] pt-2">
              {!atBottom && messages.length > 0 && (
                <Button variant="outline" size="icon-sm" aria-label="최신으로"
                  className="absolute -top-9 left-1/2 -translate-x-1/2 rounded-full shadow-md"
                  onClick={() => scrollToBottom()}>
                  <ArrowDown className="size-4" />
                </Button>
              )}
              {ask.isError && <p className="pb-1.5 text-xs text-destructive">질문을 보내지 못했습니다. 입력은 보존되어 있으니 다시 시도해주세요.</p>}
              <Composer value={question} onChange={setQuestion} onSubmit={submit} busy={busy}
                placeholder={composerPlaceholder} quote={quote} onClearQuote={() => setQuote(null)}
                hint={awaiting ? "답변을 생성하는 동안에는 이어서 질문할 수 없습니다" : undefined} />
            </div>
          </>
        )}
      </section>
    </div>
  )
}
