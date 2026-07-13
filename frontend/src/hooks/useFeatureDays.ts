import { useQuery } from "@tanstack/react-query"
import { apiQuery, postJson, STALE } from "@/api/query"

export interface FeatureDay {
  date: string
  ret_pct: number
  volume_ratio: number | null
  direction: "up" | "down"
  note: string | null
  note_status: string | null
}

export interface DayExplain {
  note: string | null
  status: string   // ok | no_docs | failed | unavailable
  docs: { id: number; title: string }[]
}

/** 특징일 마커 목록 — 하이닉스·삼성전자만 LLM 테스트 대상 (그 외는 마커만 감지) */
export function useFeatureDays(stockCode: string) {
  return useQuery(
    apiQuery<{ stock_code: string; days: FeatureDay[] }>({
      key: ["spine", "feature-days", stockCode],
      url: `/api/spine/stock/${stockCode}/feature-days`,
      staleTime: STALE.medium,
      enabled: !!stockCode,
    }),
  )
}

/** 마커 클릭 시 원인 조사 (게으른 haiku 1콜 → 영구 캐시) */
export function explainFeatureDay(stockCode: string, day: string): Promise<DayExplain> {
  return postJson<DayExplain>(`/api/spine/stock/${stockCode}/feature-days/${day}/explain`)
}
