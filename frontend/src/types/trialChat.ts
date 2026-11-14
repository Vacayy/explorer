export interface TrialChatSession {
  remaining: number
  limit: number
  csrf_token: string
}

export interface TrialChatCitation {
  id: string
  title: string
  url: string
}

export interface TrialChatReply {
  answer: string
  citations: TrialChatCitation[]
  partial: boolean
  remaining: number
}

export interface TrialChatHistory {
  role: 'user' | 'assistant'
  content: string
}

export interface TrialChatInput {
  question: string
  history: TrialChatHistory[]
  search_query?: string
  document_ids?: number[]
}

export type TrialChatMessage = TrialChatHistory & {
  citations?: TrialChatCitation[]
  partial?: boolean
}
