import { useState } from "react"
import { MessageCircleQuestion, Send } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { conversationsQuery, conversationDetailQuery } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { formatRelativeTime } from "@/utils/format"

/**
 * 내가 물어본 것들 — 이 종목에 앵커/링크된 대화 스레드 (P2-1).
 * P2-0이 쌓는 질문 히스토리의 첫 노출 지점 — 클릭 시 인라인 펼침 (P2-2에서 스레드 UI로).
 */
export default function AskedSection({ stockCode }: { stockCode: string }) {
  const { data: items = [] } = useQuery(conversationsQuery(stockCode))
  if (items.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm">내가 물어본 것들</CardTitle>
        <Link to="/ask" className="ml-auto text-[11px] text-muted-foreground hover:text-primary">
          새 질문 →
        </Link>
      </CardHeader>
      <CardContent className="divide-y">
        {items.slice(0, 8).map((c) => (
          <ThreadRow key={c.id} id={c.id} title={c.title} channel={c.channel}
            count={c.message_count} updatedAt={c.updated_at} />
        ))}
      </CardContent>
    </Card>
  )
}

function ThreadRow({ id, title, channel, count, updatedAt }: {
  id: number
  title: string | null
  channel: string
  count: number
  updatedAt: string
}) {
  const [open, setOpen] = useState(false)
  const detail = useQuery(conversationDetailQuery(id, open))

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="py-1.5">
      <CollapsibleTrigger className="flex items-center gap-2 w-full text-left group">
        {channel === "telegram"
          ? <Send className="h-3 w-3 text-muted-foreground shrink-0" />
          : <MessageCircleQuestion className="h-3 w-3 text-muted-foreground shrink-0" />}
        <span className="text-xs truncate group-hover:underline">{title || "(제목 없음)"}</span>
        <Badge variant="secondary" className="text-[9px] shrink-0">{count}</Badge>
        <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
          {formatRelativeTime(updatedAt)}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        {detail.data && (
          <div className="mt-1.5 space-y-1.5 border-l-2 border-border pl-3">
            {detail.data.messages.map((m) => (
              <div key={m.id} className="text-xs">
                <span className={m.role === "user" ? "font-semibold" : "text-hypothesis font-semibold"}>
                  {m.role === "user" ? "Q" : "A"}
                </span>{" "}
                <span className={m.role === "assistant" ? "text-muted-foreground" : ""}>
                  {m.content.length > 400 ? m.content.slice(0, 400) + "…" : m.content}
                </span>
              </div>
            ))}
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
