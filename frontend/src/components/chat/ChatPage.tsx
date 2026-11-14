import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom"
import { ArrowDown, BookOpen, ChevronLeft, Link2, Send } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { ErrorState } from "@/components/shared/ErrorState"
import { useChat } from "@/hooks/useChat"
import { useChatStudy } from "@/hooks/useChatStudy"
import { MOBILE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery"
import { useThreadTargets } from "@/hooks/useThreadTargets"
import { sendable, toPayload } from "@/lib/chatTargets"
import { AssistantMessage, StreamingMessage } from "./AssistantMessage"
import { carriedFollowUps } from "./FollowUps"
import type { Quote as QuoteRef } from "./useQuoteSelection"
import { ChatEmpty } from "./ChatEmpty"
import { Composer } from "./Composer"
import { ThreadRail } from "./ThreadRail"
import { UserMessage } from "./UserMessage"
import { ThreadTitle } from "./ThreadTitle"

/** 스크롤 컨테이너 하단에서 이 거리 이내면 "바닥" — 자동 스크롤 허용 */
const BOTTOM_PX = 80

/**
 * /chat — AI 대화 (시안 Chat, ia-redesign §4.14). 화면 스펙: docs/specs/chat-page.md.
 * 왼쪽 대화 목록 260px(폭 <1024는 Sheet) | 800px 읽기 칸(제목 · 스터디로 만들기 · 공유 링크 → 문답) + 아래 고정 입력 카드.
 * URL ?id= 가 활성 스레드의 단일 상태 소스, ?q= 는 옴니바 프리필. 데이터·진행 규약은 hooks/useChat.ts.
 */
export default function ChatPage() {
  const [searchParams] = useSearchParams()
  const legacyParams = new URLSearchParams(searchParams)
  legacyParams.delete('mode')
  return searchParams.get('mode') === 'analysis'
    ? <Navigate to={`/discover${legacyParams.size ? `?${legacyParams}` : ''}`} replace />
    : <ConversationPage />
}

function ConversationPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeId = searchParams.get("id") ? Number(searchParams.get("id")) : null
  const [question, setQuestion] = useState(searchParams.get("q") ?? "")
  const [quote, setQuote] = useState<QuoteRef | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const phone = useMediaQuery(MOBILE_QUERY)
  const navigate = useNavigate()
  const { makeStudy } = useChatStudy()

  const chat = useChat(activeId, id => openThread(id))
  const { detail, messages, awaiting, stalled, draft, ask } = chat
  // 붙인 대상 — 대화 내내 남는다(ia-redesign §4.14a). 이 화면에 있을 때 ⌘K 'AI에게 묻기'도 여기 붙는다
  const { targets, setTargets, reset: resetTargets } = useThreadTargets(activeId, detail.data)

  const openThread = useCallback((id: number) => {
    if (id !== activeId) resetTargets()
    setSearchParams({ id: String(id) })
    setSheetOpen(false)
  }, [activeId, resetTargets, setSearchParams])
  const newThread = () => { setSearchParams({}); setQuestion(""); setQuote(null); resetTargets(); setSheetOpen(false) }
  const carried = useMemo(() => carriedFollowUps(messages), [messages])
  const busy = ask.isPending || awaiting

  const submit = (text?: string) => {
    const q = (text ?? question).trim()
    const withQuote = text === undefined ? quote : null
    // 인용만 붙이고 전송해도 된다 — "이 대목 더 설명해줘"가 기본 의도
    if ((!q && !withQuote) || busy) return
    ask.mutate(
      { question: q || "이 대목을 더 자세히 설명해줘", conversation_id: activeId ?? undefined, quote: withQuote ?? undefined,
        attachments: toPayload(targets) },
      { onSuccess: () => { setTargets(sendable(targets)); if (text === undefined) { setQuestion(""); setQuote(null) } } },
    )
    stickRef.current = true
  }
  /** '다시 답변' — 마지막 답의 질문을 같은 대화에 다시 보낸다(새 답이 아래에 붙는다) */
  const lastQuestion = useMemo(() => [...messages].reverse().find(m => m.role === "user")?.content ?? null, [messages])

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
  const threadTitle = thread?.title || "대화"
  const composerPlaceholder = activeId ? "이어서 물어보기" : "무엇이든 물어보세요"
  const toStudy = () => makeStudy.mutate({ title: threadTitle, messages }, {
    onSuccess: r => { toast.success(r.added ? `스터디를 만들고 자료 ${r.added}건을 넣었습니다.` : "스터디를 만들었습니다."); navigate(`/study/projects/${r.id}`) },
    onError: () => toast.error("스터디를 만들지 못했습니다. 다시 시도해 주세요."),
  })
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(`${window.location.origin}/chat?id=${activeId}`); toast.success("대화 링크를 복사했습니다.") }
    catch { toast.error("링크를 복사하지 못했습니다.") }
  }

  return (
    <div className="flex h-[calc(100dvh-var(--shell-offset))]">
      {/* 대화 목록 — 폭 1024 이상은 왼쪽 칸 */}
      <aside className="hidden w-[260px] shrink-0 border-r lg:block" aria-label="대화 목록">
        <ThreadRail threads={chat.threads} loading={chat.threadsLoading} error={chat.threadsError}
          activeId={activeId} onSelect={openThread} onNew={newThread} />
      </aside>
      {/* 폰·태블릿 — Sheet */}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="left" className="w-[300px] p-0 pt-10 sm:max-w-[300px]">{/* pt-10: Sheet 닫기 버튼이 '새 대화'를 가리지 않게 */}
          <SheetTitle className="sr-only">대화 목록</SheetTitle>
          <ThreadRail threads={chat.threads} loading={chat.threadsLoading} error={chat.threadsError}
            activeId={activeId} onSelect={openThread} onNew={newThread} />
        </SheetContent>
      </Sheet>

      {/* 본문 */}
      <section className="flex min-w-0 flex-1 flex-col lg:pl-6">
        {/* 폭 <1024 머리 — '‹ 대화 목록' · (폰은 제목) · '새 대화' (ia-redesign §4.32) */}
        <header className="flex h-10 shrink-0 items-center gap-2 lg:hidden">
          <Button variant="ghost" size="sm" className="-ml-2 h-10 shrink-0 gap-0.5 px-2" onClick={() => setSheetOpen(true)}>
            <ChevronLeft className="size-4" aria-hidden />대화 목록
          </Button>
          {thread && phone && <ThreadTitle id={thread.id} title={thread.title} />}
          {activeId && <Button variant="ghost" size="sm" className="ml-auto h-10 shrink-0 px-2" onClick={newThread}>새 대화</Button>}
        </header>

        {!activeId && !ask.isPending ? (
          /* Empty — 인사 + 중앙 컴포저 + 제안 카드 */
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ChatEmpty onPick={setQuestion}>
              <Composer value={question} onChange={setQuestion} onSubmit={() => submit()} busy={busy}
                placeholder={composerPlaceholder} autoFocus quote={quote} onClearQuote={() => setQuote(null)}
                targets={targets} onTargetsChange={setTargets} />
              {ask.isError && <p className="pt-2 text-center text-xs text-destructive">질문을 보내지 못했습니다. 다시 시도해주세요.</p>}
            </ChatEmpty>
          </div>
        ) : (
          <>
            {/* 메시지 스트림 */}
            <div ref={scrollRef} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-[800px] space-y-8 px-1 pt-1 pb-6 lg:pt-2">
                {thread && (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      {!phone && <ThreadTitle id={thread.id} title={thread.title} size="lg" />}
                      {thread.channel === "telegram" && (
                        <Badge variant="outline" className="shrink-0 gap-1 text-[10px] font-normal"><Send className="size-2.5" /> 텔레그램</Badge>
                      )}
                      <span className="ml-auto flex shrink-0 items-center gap-1.5">
                        {thread.study_project
                          ? <Button variant="outline" size="sm" className="rounded-full" asChild><Link to={`/study/projects/${thread.study_project.id}`}><BookOpen className="size-3.5" aria-hidden />스터디 열기</Link></Button>
                          : thread.study
                            ? <Button variant="outline" size="sm" className="rounded-full" asChild><Link to={`/study/${thread.study.id}`}><BookOpen className="size-3.5" aria-hidden />스터디 열기</Link></Button>
                            : <Button variant="outline" size="sm" className="rounded-full" disabled={makeStudy.isPending || !messages.length} onClick={toStudy}>
                                {makeStudy.isPending ? <Spinner className="size-3.5" /> : <BookOpen className="size-3.5" aria-hidden />}스터디로 만들기
                              </Button>}
                        <Button variant="ghost" size="sm" className="rounded-full" onClick={copyLink}><Link2 className="size-3.5" aria-hidden />공유 링크</Button>
                      </span>
                    </div>
                  </div>
                )}
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
                    ? <UserMessage key={m.id} content={m.content} attachments={m.attachments} onReask={setQuestion} />
                    : <AssistantMessage key={m.id} m={m} isLast={i === messages.length - 1} carried={carried}
                        attachedCount={messages[i - 1]?.role === "user" ? messages[i - 1].attachments?.length : undefined}
                        onQuote={setQuote} onPick={setQuestion} conversationId={activeId} threadTitle={threadTitle}
                        onRegenerate={i === messages.length - 1 && !busy && lastQuestion ? () => submit(lastQuestion) : undefined} />
                )}
                {/* 제출 직후 찰나(서버 적재 전) — 낙관적 표시 */}
                {ask.isPending && <UserMessage content={ask.variables?.question ?? ""} attachments={ask.variables?.attachments} pending />}
                {(awaiting || ask.isPending) && <StreamingMessage draft={draft} />}
                {stalled && (
                  <p className="rounded-xl border border-destructive/30 px-4 py-3 text-[13px] text-destructive">
                    답변 생성이 멈춘 것 같습니다 (5분 초과). 서버 상태를 확인하고 다시 질문해주세요.
                  </p>
                )}
              </div>
            </div>

            {/* 컴포저 — 하단 고정 */}
            <div className="relative mx-auto w-full max-w-[800px] pt-2">
              {!atBottom && messages.length > 0 && (
                <Button variant="outline" size="icon-sm" aria-label="최신으로"
                  className="absolute -top-9 left-1/2 -translate-x-1/2 rounded-full shadow-md"
                  onClick={() => scrollToBottom()}>
                  <ArrowDown className="size-4" />
                </Button>
              )}
              {ask.isError && <p className="pb-1.5 text-xs text-destructive">질문을 보내지 못했습니다. 입력은 보존되어 있으니 다시 시도해주세요.</p>}
              <Composer value={question} onChange={setQuestion} onSubmit={() => submit()} busy={busy}
                placeholder={composerPlaceholder} quote={quote} onClearQuote={() => setQuote(null)}
                targets={targets} onTargetsChange={setTargets}
                hint={awaiting ? "답변을 만드는 동안에는 이어서 질문할 수 없습니다" : undefined} />
            </div>
          </>
        )}
      </section>
    </div>
  )
}
