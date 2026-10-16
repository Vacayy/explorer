import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"

export interface AiActivityItem {
  type: string; title: string; topic: string; code: string | null; question_id?: number | null; doc_id?: number | null; created_at: string
}

/** 'AI가 최근 만든 것' 기간·상한 — 피드 상단과 캔버스 위젯이 같은 응답(같은 쿼리 키)을 쓴다 */
export const AI_ACTIVITY = { days: 7, limit: 30 } as const

/** AI 생성물 최신순 (GET /api/spine/home/ai-activity, 읽기만) */
export function useAiActivity() {
  return useQuery(apiQuery<AiActivityItem[]>({
    key: ["spine", "home", "ai-activity", AI_ACTIVITY.days, AI_ACTIVITY.limit],
    url: `/api/spine/home/ai-activity?days=${AI_ACTIVITY.days}&limit=${AI_ACTIVITY.limit}`,
    staleTime: STALE.short,
  }))
}
