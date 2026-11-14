import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { flushUsage, inPageEvents, placeOf, screenOf, track, type Screen } from '@/lib/usage'

/** 입력이 이만큼 없으면 머문 시간 시계를 멈춘다(켜 두고 자리를 비운 시간을 빼려고). 입력이 오면 다시 센다 */
export const IDLE_CAP_MS = 5 * 60_000
const INPUTS = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'scroll', 'touchstart'] as const

type Current = Screen & { section?: string; tab?: string; visibleSince: number | null; dwell: number }

/** 화면 진입·이탈과 보이는 동안 머문 시간을 남긴다(docs/specs/observability.md). 레이아웃에 한 번만 둔다.
 * 같은 화면 안에서 상태 쿼리(group·stock·hs·tw 등)만 바뀌면 새 방문이 아니라 동작·열람 하나로 남긴다. */
export function UsageTracker() {
  const { pathname, search } = useLocation()
  const cur = useRef<Current | null>(null)
  const idleTimer = useRef<number | null>(null)
  const lastInput = useRef(0)

  /** 시계를 멈추고 지금까지 센 시간을 더한다(at = 멈춘 시각) */
  const pause = (at = Date.now()) => {
    const c = cur.current
    if (c?.visibleSince != null) { c.dwell += Math.max(0, at - c.visibleSince); c.visibleSince = null }
  }
  const armIdle = () => {
    if (idleTimer.current != null) window.clearTimeout(idleTimer.current)
    idleTimer.current = window.setTimeout(() => { idleTimer.current = null; pause(lastInput.current + IDLE_CAP_MS) }, IDLE_CAP_MS)
  }
  /** 입력·화면 진입 — 멈춘 시계를 다시 켜고 무입력 타이머를 새로 건다 */
  const touch = () => {
    const now = Date.now()
    lastInput.current = now
    const c = cur.current
    if (c && c.visibleSince == null && document.visibilityState === 'visible') c.visibleSince = now
    armIdle()
  }

  const leave = () => {
    const c = cur.current
    if (!c) return
    const dwell = c.dwell + (c.visibleSince ? Date.now() - c.visibleSince : 0)
    track('leave', c.name, { entity: c.entity, dwell_ms: Math.round(dwell), section: c.section, tab: c.tab })
  }

  useEffect(() => {
    const next = screenOf(pathname, search)
    const c = cur.current
    const inPage = c && inPageEvents(c, next)
    if (c && inPage) {
      for (const e of inPage) track(e.type, e.name, { entity: e.entity, ref: c.name, section: c.section, tab: c.tab })
      c.keys = next.keys
      touch()
      return
    }
    const ref = c?.name
    leave()
    const place = placeOf(pathname, search)
    cur.current = { ...next, ...place, visibleSince: document.visibilityState === 'visible' ? Date.now() : null, dwell: 0 }
    track('view', next.name, { ref, entity: next.entity, section: place.section, tab: place.tab })
    touch()
  }, [pathname, search])

  useEffect(() => {
    let last = 0
    const onInput = () => {
      const now = Date.now()
      if (now - last < 1000 && cur.current?.visibleSince != null) return   // 잦은 입력(mousemove)은 1초에 한 번만
      last = now
      touch()
    }
    const onVis = () => {
      const c = cur.current
      if (!c) return
      if (document.visibilityState === 'hidden') {
        pause()
        leave()   // 탭을 숨기거나 닫으면 여기서 끝날 수 있다 — 머문 시간을 남기고 보낸다
        c.dwell = 0
        flushUsage()
      } else {
        touch()
      }
    }
    for (const t of INPUTS) window.addEventListener(t, onInput, { capture: true, passive: true })
    document.addEventListener('visibilitychange', onVis)
    return () => {
      for (const t of INPUTS) window.removeEventListener(t, onInput, { capture: true })
      document.removeEventListener('visibilitychange', onVis)
      if (idleTimer.current != null) window.clearTimeout(idleTimer.current)
    }
  }, [])

  return null
}
