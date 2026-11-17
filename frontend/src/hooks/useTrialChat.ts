import { useCallback, useEffect, useRef, useState } from 'react'
import api from '@/api/client'
import { isCancelled, toApiError } from '@/api/errors'
import type { TrialChatInput, TrialChatMessage, TrialChatReply, TrialChatSession } from '@/types/trialChat'

const SESSION_URL = '/api/public/chat/session'
const CHAT_URL = '/api/public/chat'

function failureMessage(status?: number) {
  if (status === 429) return '체험 사용 한도에 도달했거나 다른 요청이 진행 중입니다. 잠시 후 확인해 주세요.'
  if (status === 403) return '체험 세션을 다시 확인한 뒤 보내 주세요.'
  if (status === 404) return '답변에 사용할 공개 자료를 찾지 못했습니다.'
  if (status === 409) return '공개 자료가 변경되어 답변을 제공할 수 없습니다. 다시 질문해 주세요.'
  if (status === 413 || status === 422) return '질문이나 대화가 너무 길거나 입력 형식이 올바르지 않습니다.'
  return '답변을 받지 못했습니다. 사용 가능 횟수를 확인한 뒤 다시 시도해 주세요.'
}

/** No query/mutation cache or browser storage: this hook owns the entire conversation.
 * Pass the verified account identity as scopeKey when mounted across account changes.
 */
export function useTrialChat(scopeKey = 'anonymous') {
  const [session, setSession] = useState<TrialChatSession | null>(null)
  const [messages, setMessages] = useState<TrialChatMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)
  const sessionRef = useRef<TrialChatSession | null>(null)
  const messagesRef = useRef<TrialChatMessage[]>([])
  const busy = useRef(false)
  const controllers = useRef(new Set<AbortController>())

  const readSession = useCallback(async (epoch: number) => {
    const controller = new AbortController()
    controllers.current.add(controller)
    try {
      const { data } = await api.get<TrialChatSession>(SESSION_URL, {
        withCredentials: true, signal: controller.signal,
      })
      if (generation.current !== epoch || controller.signal.aborted) return false
      sessionRef.current = data
      setSession(data)
      return true
    } catch {
      if (generation.current === epoch && !controller.signal.aborted) {
        sessionRef.current = null
        setSession(null)
      }
      return false
    } finally {
      controllers.current.delete(controller)
    }
  }, [])

  const clear = useCallback(() => {
    generation.current += 1
    for (const controller of controllers.current) controller.abort()
    controllers.current.clear()
    sessionRef.current = null
    messagesRef.current = []
    busy.current = false
    return generation.current
  }, [])

  const reset = useCallback(async () => {
    const epoch = clear()
    setSession(null)
    setMessages([])
    setError(null)
    setSending(false)
    setLoading(true)
    const success = await readSession(epoch)
    if (generation.current !== epoch) return
    setLoading(false)
    if (!success) setError('체험 서비스를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.')
  }, [clear, readSession])

  useEffect(() => {
    void reset()
    return () => { clear() }
  }, [scopeKey, reset, clear])

  const send = useCallback(async (question: string, options: Pick<TrialChatInput, 'document_ids' | 'search_query'> = {}) => {
    const current = sessionRef.current
    if (busy.current || !current || current.remaining <= 0 || !question.trim()) return false
    busy.current = true
    setSending(true)
    setError(null)
    const epoch = generation.current
    const controller = new AbortController()
    controllers.current.add(controller)
    const history = messagesRef.current.slice(-4).map(({ role, content }) => ({ role, content }))
    const body: TrialChatInput = { question, history, ...options }
    try {
      const { data } = await api.post<TrialChatReply>(CHAT_URL, body, {
        headers: { 'X-CSRF-Token': current.csrf_token }, withCredentials: true,
        timeout: 200_000, signal: controller.signal,
      })
      if (generation.current !== epoch || controller.signal.aborted) return false
      const next: TrialChatMessage[] = [...messagesRef.current,
        { role: 'user', content: question },
        { role: 'assistant', content: data.answer, citations: data.citations, partial: data.partial }]
      messagesRef.current = next
      setMessages(next)
      const nextSession = { ...current, remaining: data.remaining }
      sessionRef.current = nextSession
      setSession(nextSession)
      return true
    } catch (cause) {
      if (generation.current !== epoch || controller.signal.aborted || isCancelled(cause)) return false
      // Keep only fixed UI text, never the Axios config/body/response in state.
      const message = failureMessage(toApiError(cause).status)
      sessionRef.current = null
      setSession(null)
      await readSession(epoch)
      if (generation.current === epoch) setError(message)
      return false
    } finally {
      controllers.current.delete(controller)
      if (generation.current === epoch) {
        busy.current = false
        setSending(false)
      }
    }
  }, [readSession])

  const status = loading ? 'loading' : sending ? 'sending' : error ? 'error'
    : messages.length === 0 ? 'empty' : messages.some(message => message.partial) ? 'partial' : 'ideal'
  return { session, messages, loading, sending, error, status, send, reset }
}
