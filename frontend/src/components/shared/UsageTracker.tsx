import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { flushUsage, screenOf, track } from '@/lib/usage'

/** 화면 진입·이탈과 보이는 동안 머문 시간을 남긴다(docs/specs/observability.md). 레이아웃에 한 번만 둔다. */
export function UsageTracker() {
  const { pathname, search } = useLocation()
  const cur = useRef<{ name: string; entity?: string; visibleSince: number | null; dwell: number } | null>(null)

  const leave = () => {
    const c = cur.current
    if (!c) return
    const dwell = c.dwell + (c.visibleSince ? Date.now() - c.visibleSince : 0)
    track('leave', c.name, { entity: c.entity, dwell_ms: Math.round(dwell) })
  }

  useEffect(() => {
    const next = screenOf(pathname, search)
    if (cur.current && cur.current.name === next.name && cur.current.entity === next.entity) return
    const ref = cur.current?.name
    leave()
    cur.current = { ...next, visibleSince: document.visibilityState === 'visible' ? Date.now() : null, dwell: 0 }
    track('view', next.name, { ref, entity: next.entity })
  }, [pathname, search])

  useEffect(() => {
    const onVis = () => {
      const c = cur.current
      if (!c) return
      if (document.visibilityState === 'hidden') {
        if (c.visibleSince) { c.dwell += Date.now() - c.visibleSince; c.visibleSince = null }
        leave()   // 탭을 숨기거나 닫으면 여기서 끝날 수 있다 — 머문 시간을 남기고 보낸다
        c.dwell = 0
        flushUsage()
      } else if (!c.visibleSince) {
        c.visibleSince = Date.now()
      }
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  return null
}
