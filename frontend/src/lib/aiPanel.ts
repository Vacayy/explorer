import type { Quote } from "@/components/chat/useQuoteSelection"
import type { ChatTarget } from "@/types"

/**
 * 'AI에게 묻기' 다리 (docs/specs/canvas.md §2) — 어느 화면에서든 선택 문장을 오른쪽 AI 패널로 보낸다.
 * 셸(Layout)은 이벤트를 듣고 패널을 연다. 패널이 닫혀 있어 아직 없으면 마운트할 때 대기 중인 요청을 가져간다.
 */
export interface AskAiRequest {
  quote: Quote
  /** 미리 채울 질문 — 없으면 인용만 붙이고 입력창에 포커스 */
  question?: string
  /** true면 바로 보낸다(설명·검토처럼 질문이 정해진 동작) */
  send?: boolean
}

export const ASK_AI_EVENT = "explorer:ask-ai"
let pending: AskAiRequest | null = null

export function askAi(req: AskAiRequest) {
  pending = req
  window.dispatchEvent(new CustomEvent<AskAiRequest>(ASK_AI_EVENT, { detail: req }))
}

/** 패널이 처리할 요청을 가져간다(한 번만) */
export function takePendingAsk(): AskAiRequest | null {
  const p = pending
  pending = null
  return p
}

export function onAskAi(fn: (req: AskAiRequest) => void): () => void {
  const h = (e: Event) => fn((e as CustomEvent<AskAiRequest>).detail)
  window.addEventListener(ASK_AI_EVENT, h)
  return () => window.removeEventListener(ASK_AI_EVENT, h)
}

/** 질문·인용 없이 AI 패널만 연다 — 모바일 문서 화면의 '이 자료로 대화'(ia-redesign §4.32). 보는 화면은 패널이 자동 첨부한다 */
export const OPEN_AI_EVENT = "explorer:open-ai"
export function openAi() {
  window.dispatchEvent(new Event(OPEN_AI_EVENT))
}
export function onOpenAi(fn: () => void): () => void {
  window.addEventListener(OPEN_AI_EVENT, fn)
  return () => window.removeEventListener(OPEN_AI_EVENT, fn)
}

/** 읽던 자료에서 고른 문장 → AI 패널. 설명·검토는 질문이 정해져 있어 바로 보낸다 */
export const ASK_PRESET = {
  explain: "이 대목을 쉽게 풀어 설명해줘. 깔린 전제와 용어도 짚어줘.",
  critique: "이 대목의 주장과 근거를 검토해줘. 빠진 근거·반대 근거·확인할 점을 짚어줘.",
} as const
export function askAboutText(sel: { selected: string; block: string }, source: { docId?: number | null; title?: string | null },
  preset?: keyof typeof ASK_PRESET) {
  askAi({
    quote: { doc_id: source.docId ?? undefined, doc_title: source.title || undefined, selected: sel.selected, block: sel.block, citations: [] },
    question: preset ? ASK_PRESET[preset] : undefined,
    send: !!preset,
  })
}

/**
 * ⌘K 'AI에게 묻기' (ia-redesign §4.14a, D-311) — AI 대화를 열고 대상을 붙여 둔다. 질문은 보내지 않는다.
 * 셸은 패널을 열고(대화 화면이면 그 화면이 받는다), 패널·대화 화면이 마운트할 때 대기 중인 대상을 가져간다.
 */
export const ATTACH_AI_EVENT = "explorer:attach-ai"
let pendingTarget: ChatTarget | null = null
export function attachToAi(target: ChatTarget) {
  pendingTarget = target
  window.dispatchEvent(new CustomEvent<ChatTarget>(ATTACH_AI_EVENT, { detail: target }))
}
export function takePendingTarget(): ChatTarget | null {
  const t = pendingTarget
  pendingTarget = null
  return t
}
export function onAttachAi(fn: (t: ChatTarget) => void): () => void {
  const h = (e: Event) => fn((e as CustomEvent<ChatTarget>).detail)
  window.addEventListener(ATTACH_AI_EVENT, h)
  return () => window.removeEventListener(ATTACH_AI_EVENT, h)
}
