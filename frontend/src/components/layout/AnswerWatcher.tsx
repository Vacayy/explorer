import { useEffect } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { toast } from "sonner"
import api from "@/api/client"
import { getPendingAnswers, removePendingAnswer } from "@/lib/pendingAnswers"
import type { ConversationDetail } from "@/types"

/**
 * 전역 '답변 도착' 감시자 — 어느 화면에 있든 서버 이벤트를 사용자에게 알린다.
 * 생성 중인 스레드가 있을 때만 8초 폴링, 답변이 붙으면 토스트 + 보러가기.
 * (해당 스레드를 이미 보고 있으면 조용히 해제 — 화면 폴링이 처리)
 */
export default function AnswerWatcher() {
  const navigate = useNavigate()
  const { pathname, search } = useLocation()

  useEffect(() => {
    const timer = setInterval(async () => {
      const ids = getPendingAnswers()
      if (ids.length === 0) return
      for (const id of ids) {
        try {
          const { data } = await api.get<ConversationDetail>(`/api/spine/conversations/${id}`)
          const last = data.messages[data.messages.length - 1]
          if (!last || last.role !== "assistant") continue
          removePendingAnswer(id)
          const viewing = pathname.startsWith("/chat") && new URLSearchParams(search).get("id") === String(id)
          if (!viewing) {
            toast.success(`답변 도착 — ${data.title ?? "질문"}`, {
              duration: 10000,
              action: { label: "보러가기", onClick: () => navigate(`/chat?id=${id}`) },
            })
          }
        } catch {
          removePendingAnswer(id)  // 삭제된 스레드 등 — 감시 중단
        }
      }
    }, 8000)
    return () => clearInterval(timer)
  }, [pathname, search, navigate])

  return null
}
