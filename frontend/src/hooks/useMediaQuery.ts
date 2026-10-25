import { useSyncExternalStore } from "react"

/** CSS 미디어 쿼리 일치 여부 — 창 크기가 바뀌면 다시 그린다 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    notify => {
      const mq = window.matchMedia(query)
      mq.addEventListener("change", notify)
      return () => mq.removeEventListener("change", notify)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** 앱 셸 분기점 — <768 모바일(하단 탭바), <1024 AI 대화는 오버레이 (docs/specs/app-shell.md §6) */
export const MOBILE_QUERY = "(max-width: 767px)"
export const PANEL_INLINE_QUERY = "(min-width: 1024px)"
