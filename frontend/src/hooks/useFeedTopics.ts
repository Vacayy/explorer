import { useQuery } from '@tanstack/react-query'
import { apiQuery, STALE } from '@/api/query'
import { useSpineSignals } from '@/hooks/useSpineSignals'

const LIMIT = 5

/**
 * 피드 상단 주제 칩 (D-208) — 주목 주제(theme_surge, 지금 비중순)와 부상 종목(언급 모멘텀) 상위 5.
 * 칩은 피드를 거르는 진입점이라 이름만 쓴다. 두 출처는 독립 실패한다.
 */
export function useFeedTopics() {
  const themes = useSpineSignals('theme_surge', 14)
  const momentum = useQuery(apiQuery<{ items: { entity_id: number; name: string }[] }>({
    key: ['spine', 'momentum'], url: '/api/spine/signals/momentum', staleTime: STALE.medium,
  }))
  const themeNames = [...(themes.data?.items ?? [])]
    .sort((a, b) => (b.payload.share_pct ?? -1) - (a.payload.share_pct ?? -1))
    .slice(0, LIMIT).map(s => s.entity_name)
  const dates = (themes.data?.items ?? []).map(s => s.date).sort()
  return {
    themes: [...new Set(themeNames)],
    stocks: [...new Set((momentum.data?.items ?? []).slice(0, LIMIT).map(m => m.name))],
    // 위젯용 상태 — 피드 칩 줄은 쓰지 않는다(로딩·오류면 줄을 생략)
    asOf: dates.at(-1) ?? null,
    isLoading: themes.isLoading || momentum.isLoading,
    isError: themes.isError && momentum.isError,
    refetch: () => { void themes.refetch(); void momentum.refetch() },
  }
}
