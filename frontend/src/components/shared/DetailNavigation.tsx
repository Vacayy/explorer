import { getHomeMode } from "@/hooks/useHomeMode"
import { sessionMemory } from "@/lib/sessionMemory"
import { useLayoutEffect } from 'react'
import { Link, useLocation, useNavigate, useNavigationType, type LinkProps } from 'react-router-dom'

type Origin = { url: string; key: string; index: number; label: string; state: unknown }
const positions = sessionMemory<{ y: number; focus: string }>('explorer.detail.positions')
const pathLabel = (path: string) => path.startsWith('/home') || path.startsWith('/feed') ? '피드' : path.startsWith('/doc/') ? '자료' : path.startsWith('/narrative') ? '내러티브' : '이전 화면'

export function useDetailOrigin() {
  const location = useLocation()
  return { url: location.pathname + location.search + location.hash, key: location.key,
    index: window.history.state?.idx ?? -1, label: location.pathname === "/home" ? (getHomeMode(location.search) === "feed" ? "피드" : "Home") : pathLabel(location.pathname), state: location.state } satisfies Origin
}
export function rememberDetailOrigin(origin: Origin, focus = '') {
  positions.set(origin.key, { y: window.scrollY, focus })
}
export function DetailLink({ onClick, state, ...props }: LinkProps) {
  const origin = useDetailOrigin()
  const focus = typeof props.to === 'string' ? props.to : props.to.pathname || ''
  return <Link {...props} data-detail-link={focus} state={{ ...state, detailOrigin: origin }} onClick={event => {
    onClick?.(event)
    if (!event.defaultPrevented && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) rememberDetailOrigin(origin, focus)
  }} />
}
export function useDetailBack(fallback: string, label: string) {
  const location = useLocation(), navigate = useNavigate()
  const origin = location.state?.detailOrigin as Origin | undefined
  const valid = origin && typeof origin.url === 'string' && origin.url.startsWith('/') && !origin.url.startsWith('//')
  return { label: valid ? `${origin.label}로 돌아가기` : label, go: () => {
    if (!valid) return navigate(fallback, { replace: true })
    const index = window.history.state?.idx
    if (typeof index === 'number' && origin.index >= 0 && index === origin.index + 1) navigate(-1)
    else navigate(origin.url, { replace: true, state: origin.state })
  } }
}

/** Restore after asynchronous content mounts; never steal focus on unrelated navigation. */
export function DetailNavigationMemory() {
  const location = useLocation(), type = useNavigationType()
  useLayoutEffect(() => {
    const saved = positions.get(location.key)
    if (!saved || (type !== 'POP' && type !== 'REPLACE')) {
      if (/^\/doc\/|^\/narrative/.test(location.pathname)) window.scrollTo(0, 0)
      return
    }
    let frame = 0
    const restore = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        window.scrollTo(0, saved.y)
        if (saved.focus) document.querySelector<HTMLElement>(`[data-detail-link="${CSS.escape(saved.focus)}"]`)?.focus({ preventScroll: true })
      })
    }
    restore()
    const observer = new MutationObserver(restore)
    observer.observe(document.body, { childList: true, subtree: true })
    const stop = () => { observer.disconnect(); cancelAnimationFrame(frame) }
    const timer = window.setTimeout(stop, 3000)
    window.addEventListener('wheel', stop, { once: true }); window.addEventListener('pointerdown', stop, { once: true }); window.addEventListener('keydown', stop, { once: true })
    return () => { stop(); clearTimeout(timer); window.removeEventListener('wheel', stop); window.removeEventListener('pointerdown', stop); window.removeEventListener('keydown', stop) }
  }, [location.key, location.pathname, type])
  return null
}
