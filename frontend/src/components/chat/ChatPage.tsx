import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ArrowDown, PanelLeft, Send, SquarePen } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { useChat } from "@/hooks/useChat"
import { cn } from "@/lib/utils"
import { AssistantMessage, StreamingMessage } from "./AssistantMessage"
import { ChatEmpty } from "./ChatEmpty"
import { Composer } from "./Composer"
import { ThreadRail } from "./ThreadRail"
import { UserMessage } from "./UserMessage"

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
  const [railOpen, setRailOpen] = useState(true)
  const [sheetOpen, setSheetOpen] = useState(false)

  const openThread = useCallback((id: number) => {
    setSearchParams({ id: String(id) })
    setSheetOpen(false)
  }, [setSearchParams])
  const newThread = () => { setSearchParams({}); setQuestion(""); setSheetOpen(false) }

  const chat = useChat(activeId, openThread)
  const { detail, messages, awaiting, stalled, draft, ask } = chat
  const busy = ask.isPending || awaiting

  const submit = () => {
    const q = question.trim()
    if (!q || busy) return
    ask.mutate({ question: q, conversation_id: activeId ?? undefined }, { onSuccess: () => setQuestion("") })
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
              <h2 className="min-w-0 truncate text-sm font-medium">{thread.title || "(제목 없음)"}</h2>
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

        {!activeId && !ask.isPending ? (
          /* Empty — 인사 + 중앙 컴포저 + 제안 카드 */
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ChatEmpty onPick={setQuestion}>
              <Composer value={question} onChange={setQuestion} onSubmit={submit} busy={busy}
                placeholder={composerPlaceholder} autoFocus />
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
                {messages.map((m) =>
                  m.role === "user"
                    ? <UserMessage key={m.id} content={m.content} onReask={setQuestion} />
                    : <AssistantMessage key={m.id} m={m} />
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
                placeholder={composerPlaceholder}
                hint={awaiting ? "답변을 생성하는 동안에는 이어서 질문할 수 없습니다" : undefined} />
            </div>
          </>
        )}
      </section>
    </div>
  )
}
