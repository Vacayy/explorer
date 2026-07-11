import { useEffect, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import { AlertTriangle, MessageCircleQuestion, Plus, Send, Sparkles } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { askQuestion, conversationsQuery, conversationDetailQuery, spineKeys } from "@/api/spine"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { formatRelativeTime } from "@/utils/format"
import { cn } from "@/lib/utils"

const GAP_LABEL: Record<string, string> = {
  unsupported: "근거 부족",
  contradiction: "모순",
  stale: "오래된 정보",
  missing: "빠진 정보",
}

const EXAMPLES = [
  "최근 SK하이닉스 관련 주요 이슈를 정리해줘",
  "메모리 반도체 사이클에 대한 시장 시각은?",
  "내 가설과 상충하는 최근 언급이 있어?",
]

/**
 * /chat — 대화 (P2-2, product-v3.md §2). 세 번째 프리미티브: 판단 인터페이스.
 * 좌측 스레드 리스트(웹·텔레그램 공용 풀) + 우측 활성 스레드 + 이어서 질문.
 * 후속질문은 이전 문답을 맥락으로 전달 (근거는 여전히 수집 문서만 — 에코챔버 방지).
 * URL ?id= 가 활성 스레드의 단일 상태 소스.
 */
export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeId = searchParams.get("id") ? Number(searchParams.get("id")) : null
  const [question, setQuestion] = useState(searchParams.get("q") ?? "")
  const qc = useQueryClient()

  const { data: threads = [], isLoading: threadsLoading } = useQuery(conversationsQuery())
  // 진행 중 상태도 서버 상태: 마지막 메시지가 user = 답변 생성 중 → 폴링.
  // 탭 이동·새로고침·기기 전환에도 유실 없음 (질문은 서버에 즉시 적재됨)
  const detail = useQuery({
    ...conversationDetailQuery(activeId ?? 0, !!activeId),
    refetchInterval: (query) => {
      const msgs = query.state.data?.messages
      return msgs && msgs.length > 0 && msgs[msgs.length - 1].role === "user" ? 2500 : false
    },
  })
  const msgs = detail.data?.messages
  const awaiting = !!msgs && msgs.length > 0 && msgs[msgs.length - 1].role === "user"

  const ask = useMutation({
    mutationFn: askQuestion,   // 서버가 질문을 즉시 적재하고 conversation_id 반환 (답변은 백그라운드)
    onSuccess: (d) => {
      setQuestion("")
      qc.invalidateQueries({ queryKey: spineKeys.conversations() })
      if (d.conversation_id) {
        qc.invalidateQueries({ queryKey: spineKeys.conversation(d.conversation_id) })
        if (d.conversation_id !== activeId) setSearchParams({ id: String(d.conversation_id) })
      }
    },
  })

  const submit = () => {
    const q = question.trim()
    if (!q || ask.isPending || awaiting) return
    ask.mutate({ question: q, conversation_id: activeId ?? undefined })
  }

  // 새 답변 도착 시 스크롤 하단으로
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [detail.data?.messages.length, ask.isPending, awaiting])

  return (
    <div className="grid grid-cols-[240px_1fr] gap-4 h-[calc(100vh-190px)]">
      {/* 스레드 리스트 */}
      <aside className="border rounded-xl overflow-y-auto">
        <div className="flex items-center justify-between px-3 py-2 border-b sticky top-0 bg-card">
          <h2 className="text-xs font-semibold">대화</h2>
          <Button variant="ghost" size="icon-xs" title="새 대화"
            onClick={() => { setSearchParams({}); setQuestion("") }}>
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
        {threadsLoading && <div className="p-3 space-y-2">
          <Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-3/4" />
        </div>}
        {!threadsLoading && threads.length === 0 && (
          <p className="p-3 text-[11px] text-muted-foreground">
            아직 대화가 없습니다. 오른쪽에서 첫 질문을 해보세요 — 텔레그램 봇 문답도 여기 쌓입니다.
          </p>
        )}
        {threads.map((t) => (
          <button
            key={t.id}
            onClick={() => setSearchParams({ id: String(t.id) })}
            className={cn(
              "w-full text-left px-3 py-2 border-l-[3px] transition-colors",
              t.id === activeId ? "bg-accent border-l-primary" : "border-l-transparent hover:bg-muted/50"
            )}
          >
            <div className="flex items-center gap-1.5">
              {t.channel === "telegram"
                ? <Send className="h-3 w-3 text-muted-foreground shrink-0" />
                : <MessageCircleQuestion className="h-3 w-3 text-muted-foreground shrink-0" />}
              <span className="text-xs truncate">{t.title || "(제목 없음)"}</span>
            </div>
            <div className="text-[10px] text-muted-foreground mt-0.5 tabular-nums">
              {t.message_count}개 · {formatRelativeTime(t.updated_at)}
            </div>
          </button>
        ))}
      </aside>

      {/* 활성 스레드 + 컴포저 */}
      <section className="flex flex-col min-w-0">
        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          {!activeId && !ask.isPending && (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-center">
              <Sparkles className="h-6 w-6 text-hypothesis" />
              <div>
                <p className="text-sm font-medium">수집된 문서를 근거로 답합니다</p>
                <p className="text-xs text-muted-foreground mt-1">
                  근거 없는 내용은 답하지 않고, 갭(근거 부족·모순·오래된 정보)을 함께 표시합니다.<br />
                  질문·후속질문은 스레드로 쌓여 종목 도시에의 "내가 물어본 것들"에 연결됩니다.
                </p>
              </div>
              <div className="flex gap-1.5 flex-wrap justify-center">
                {EXAMPLES.map((ex) => (
                  <button key={ex} onClick={() => setQuestion(ex)}
                    className="text-[11px] text-muted-foreground hover:text-foreground border rounded-full px-2.5 py-1">
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeId && detail.isLoading && (
            <div className="space-y-3 pt-2">
              <Skeleton className="h-10 w-2/3 ml-auto" />
              <Skeleton className="h-24 w-5/6" />
            </div>
          )}

          {detail.data?.messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary text-primary-foreground px-3.5 py-2 text-sm whitespace-pre-wrap">
                  {m.content}
                </div>
              </div>
            ) : (
              <AssistantMessage key={m.id} content={m.content} citations={m.citations}
                gaps={m.gaps} model={m.model} />
            )
          )}

          {/* 제출 직후 찰나 (서버 적재 전) — 낙관적 말풍선 */}
          {ask.isPending && (
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary text-primary-foreground px-3.5 py-2 text-sm opacity-70">
                {ask.variables?.question}
              </div>
            </div>
          )}
          {/* 답변 생성 중 — 서버 상태(마지막 메시지=user) 기반: 탭 이동·새로고침에도 유지 */}
          {(awaiting || ask.isPending) && (
            <div className="rounded-2xl border px-3.5 py-3 max-w-[85%] space-y-2">
              <Skeleton className="h-3.5 w-3/4" />
              <Skeleton className="h-3.5 w-full" />
              <p className="text-[11px] text-muted-foreground">검색 → 근거 취합 → 종합 생성 중… (~30초, 다른 화면에 다녀와도 계속됩니다)</p>
            </div>
          )}
          {ask.isError && (
            <p className="text-xs text-destructive">답변 생성에 실패했습니다. 다시 시도해주세요.</p>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 컴포저 */}
        <div className="pt-3 space-y-1.5">
          <Textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit() } }}
            placeholder={activeId ? "이어서 질문… (이전 문답이 맥락으로 전달됩니다)" : "질문하기… (Enter 전송, Shift+Enter 줄바꿈)"}
            rows={2}
            className="resize-none"
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">
              답변은 AI 종합 — 검증 필요 · 텔레그램 봇 문답도 이 스레드 풀에 쌓입니다
            </span>
            <Button size="sm" onClick={submit} disabled={ask.isPending || awaiting || !question.trim()}>
              <Sparkles className="h-3.5 w-3.5" /> {awaiting ? "답변 생성 중…" : activeId ? "이어서 질문" : "질문"}
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}

function AssistantMessage({ content, citations, gaps, model }: {
  content: string
  citations: { n: number; doc_id: number; title: string }[] | null
  gaps: { type: string; note: string }[] | null
  model: string | null
}) {
  return (
    <div className="max-w-[85%] space-y-1.5">
      <div className="rounded-2xl rounded-bl-sm border border-l-2 border-l-hypothesis px-3.5 py-2.5">
        <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_p]:my-1 [&_ul]:my-1 [&_li]:my-0.5">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
        {model && (
          <div className="text-right pt-1">
            <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
              AI 종합 · {model}
            </Badge>
          </div>
        )}
      </div>
      {gaps && gaps.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pl-1">
          {gaps.map((g, i) => (
            <span key={i} className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
              <AlertTriangle className="h-3 w-3 text-hypothesis" />
              <Badge variant="secondary" className="text-[9px]">{GAP_LABEL[g.type] ?? g.type}</Badge>
              {g.note}
            </span>
          ))}
        </div>
      )}
      {citations && citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pl-1">
          {citations.map((c) => (
            <Link key={c.n} to={`/doc/${c.doc_id}`}
              className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary border rounded-full px-2 py-0.5">
              <span className="max-w-[200px] truncate">[{c.n}] {c.title}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
