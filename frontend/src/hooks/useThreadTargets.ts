import { useCallback, useEffect, useRef, useState } from "react"
import { onAttachAi, takePendingTarget } from "@/lib/aiPanel"
import { addTarget, sameTarget } from "@/lib/chatTargets"
import type { ChatTarget, ConversationDetail } from "@/types"

/**
 * 대화에 붙인 대상 (ia-redesign §4.14a) — 서버의 대화 상세 `attached_refs`가 원본이고, 입력 중 붙이고 뺀 것은 여기 상태에 둔다.
 * 스레드를 처음 불러올 때 서버 목록을 받아 온다(그 전에 붙여 둔 것 — ⌘K 'AI에게 묻기' — 은 뒤에 남긴다).
 * 스레드를 바꾸거나 새 대화를 열 때는 `reset()`으로 비운다. ⌘K 'AI에게 묻기'로 온 대상도 여기서 받는다.
 */
export function useThreadTargets(activeId: number | null, detail: ConversationDetail | undefined, onAttached?: () => void) {
  const [targets, setTargets] = useState<ChatTarget[]>([])
  const synced = useRef<number | null>(null)

  useEffect(() => {
    if (!activeId) { synced.current = null; return }
    if (detail?.id !== activeId || synced.current === activeId) return
    synced.current = activeId
    const server = detail.attached_refs ?? []
    setTargets(prev => [...server, ...prev.filter(p => !server.some(s => sameTarget(s, p)))])
  }, [activeId, detail])

  const attachedRef = useRef(onAttached)
  attachedRef.current = onAttached
  useEffect(() => {
    const receive = (t: ChatTarget) => {
      takePendingTarget()
      setTargets(prev => addTarget(prev, t))
      attachedRef.current?.()
    }
    const waiting = takePendingTarget()
    if (waiting) receive(waiting)
    return onAttachAi(receive)
  }, [])

  const reset = useCallback(() => { synced.current = null; setTargets([]) }, [])
  return { targets, setTargets, reset }
}
