import { useMutation, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { track } from "@/lib/usage"
import type { ChatMessage } from "@/types"

/** 스터디 프로젝트 이름·자료 제목 상한(서버 Create·Clip 모델 max_length=160) */
const TITLE_MAX = 160
/** 한 번에 넣을 수 있는 수집 자료 수(서버 Documents 모델 max_length=30) */
const DOCS_MAX = 30

const clipTitle = (s: string) => (s.length > TITLE_MAX ? s.slice(0, TITLE_MAX - 1) + "…" : s)

/** 답변을 스터디 자료(직접 붙여넣은 자료)로 만든 본문 — 답 + 출처 목록 */
export function answerClipText(m: Pick<ChatMessage, "content" | "citations">): string {
  const sources = (m.citations ?? []).map(c => `[${c.n}] ${c.title}`)
  return sources.length ? `${m.content}\n\n출처\n${sources.join("\n")}` : m.content
}

/** 대화에서 인용한 수집 자료 id — 답변 순서대로, 중복 없이, 최대 30개 */
export function citedDocIds(messages: Pick<ChatMessage, "citations">[]): number[] {
  const ids: number[] = []
  for (const m of messages) for (const c of m.citations ?? []) {
    if (typeof c.doc_id === "number" && !ids.includes(c.doc_id)) ids.push(c.doc_id)
  }
  return ids.slice(0, DOCS_MAX)
}

async function createProject(title: string): Promise<number> {
  return (await api.post<{ id: number }>("/api/spine/study-projects", { title: clipTitle(title) })).data.id
}

/**
 * 대화 → 스터디 (ia-redesign §4.14 '스터디로 만들기'·답변 '스터디로 보내기'). 기존 스터디 API만 쓴다(LLM 없음).
 * - makeStudy: 대화 제목으로 새 프로젝트를 만들고 대화가 인용한 수집 자료를 넣는다. 인용 자료가 없으면 마지막 답변을 자료로 넣는다.
 * - sendAnswer: 답변 하나를 고른 프로젝트(0 = 새 프로젝트)에 '직접 붙여넣은 자료'로 넣는다.
 */
export function useChatStudy() {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: ["spine", "study-projects"] })

  const makeStudy = useMutation({
    mutationFn: async ({ title, messages }: { title: string; messages: ChatMessage[] }) => {
      const id = await createProject(title)
      track("action", "study.add", { entity: id })
      const docs = citedDocIds(messages)
      if (docs.length) {
        await api.post(`/api/spine/study-projects/${id}/documents`, { document_ids: docs })
        return { id, added: docs.length }
      }
      const last = [...messages].reverse().find(m => m.role === "assistant")
      if (last) await api.post(`/api/spine/study-projects/${id}/clips`, { title: clipTitle(`${title} — AI 답변`), text: answerClipText(last) })
      return { id, added: last ? 1 : 0 }
    },
    onSuccess: done,
  })

  const sendAnswer = useMutation({
    mutationFn: async ({ projectId, projectTitle, threadTitle, message }: { projectId: number; projectTitle?: string; threadTitle: string; message: ChatMessage }) => {
      const id = projectId || await createProject(threadTitle)
      track("action", "study.add", { entity: id })
      await api.post(`/api/spine/study-projects/${id}/clips`, { title: clipTitle(`${threadTitle} — AI 답변`), text: answerClipText(message) })
      return { id, title: projectId ? projectTitle ?? "" : clipTitle(threadTitle) }
    },
    onSuccess: done,
  })

  return { makeStudy, sendAnswer }
}
