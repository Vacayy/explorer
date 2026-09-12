import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { API_BASE } from "@/api/client"
import { askQuestion, conversationsQuery, conversationDetailQuery, spineKeys } from "@/api/spine"
import { addPendingAnswer } from "@/lib/pendingAnswers"

/** 생성 중 상태의 상한 — 이보다 오래 user로 끝나 있으면 서버가 죽은 것으로 보고 폴링을 멈춘다 */
export const STALL_MS = 5 * 60_000

/** SQLite datetime('now')는 타임존 표기 없는 UTC — Z를 붙여 파싱 */
export function utcMs(sqlite: string): number {
  const iso = sqlite.includes("T") ? sqlite : sqlite.replace(" ", "T")
  return new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime()
}

export interface Draft {
  text: string
  status: string
}

/**
 * /chat 데이터 층 — 스레드 목록 · 활성 스레드 상세(생성 중 폴링) · SSE 초안 · 질문 전송.
 *
 * 진행 표시(D-130): DB가 진실원천(마지막 메시지=user ⇒ 생성 중 → 2.5초 폴링). SSE 스트림은 가속기 —
 * 단계(status)와 본문 조각(delta)을 받아 초안으로 보여주고, 끊기면 폴링만으로 완주한다.
 * 질문은 서버에 즉시 적재되므로 탭 이동·새로고침·기기 전환에도 유실되지 않는다.
 */
export function useChat(activeId: number | null, onThreadCreated: (id: number) => void) {
  const qc = useQueryClient()

  const threadsQ = useQuery(conversationsQuery())

  const detail = useQuery({
    ...conversationDetailQuery(activeId ?? 0, !!activeId),
    refetchInterval: (query) => {
      const msgs = query.state.data?.messages
      const last = msgs && msgs.length > 0 ? msgs[msgs.length - 1] : null
      if (!last || last.role !== "user") return false
      return Date.now() - utcMs(last.created_at) > STALL_MS ? false : 2500
    },
  })
  const messages = detail.data?.messages ?? []
  const last = messages.length > 0 ? messages[messages.length - 1] : null
  const awaitingRaw = !!last && last.role === "user"
  const stalled = awaitingRaw && Date.now() - utcMs(last!.created_at) > STALL_MS
  const awaiting = awaitingRaw && !stalled

  // SSE 진행 스트림 — 생성 중인 활성 스레드에만 연결. 404(스트림 없음)·끊김이면 조용히 폴링으로.
  const [draft, setDraft] = useState<Draft | null>(null)
  useEffect(() => {
    if (!activeId || !awaiting) { setDraft(null); return }
    const es = new EventSource(`${API_BASE}/api/spine/conversations/${activeId}/stream`)
    const parse = (e: Event) => JSON.parse((e as MessageEvent).data) as { text?: string }
    es.addEventListener("status", (e) => setDraft((d) => ({ text: d?.text ?? "", status: parse(e).text ?? "" })))
    es.addEventListener("delta", (e) => setDraft((d) => ({ text: (d?.text ?? "") + (parse(e).text ?? ""), status: d?.status ?? "" })))
    es.addEventListener("reset", (e) => setDraft((d) => ({ text: parse(e).text ?? "", status: d?.status ?? "" })))
    es.addEventListener("done", () => {
      es.close()
      qc.invalidateQueries({ queryKey: spineKeys.conversation(activeId) })
      qc.invalidateQueries({ queryKey: spineKeys.conversations() })
    })
    es.onerror = () => es.close()
    return () => es.close()
  }, [activeId, awaiting, qc])

  const ask = useMutation({
    mutationFn: askQuestion,   // 서버가 질문을 즉시 적재하고 conversation_id 반환 (답변은 백그라운드)
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: spineKeys.conversations() })
      if (d.conversation_id) {
        addPendingAnswer(d.conversation_id)   // 다른 화면으로 가도 '답변 도착' 알림
        qc.invalidateQueries({ queryKey: spineKeys.conversation(d.conversation_id) })
        if (d.conversation_id !== activeId) onThreadCreated(d.conversation_id)
      }
    },
  })

  return {
    threads: threadsQ.data ?? [],
    threadsLoading: threadsQ.isLoading,
    threadsError: threadsQ.isError,
    detail,
    messages,
    awaiting,
    stalled,
    draft,
    ask,
  }
}
