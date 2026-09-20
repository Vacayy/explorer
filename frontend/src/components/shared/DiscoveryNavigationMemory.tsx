import { useLayoutEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { sessionMemory } from '@/lib/sessionMemory'

const positions = sessionMemory<{ y: number; focus: string }>('explorer.discovery.positions')

function workspaceKey(pathname: string, search: string) {
  const params = new URLSearchParams(search)
  if (pathname === '/discover') return `${pathname}:${params.get('run') ?? 'new'}:${params.get('candidate') ?? ''}`
  if (pathname.startsWith('/analyze/') && params.has('discovery')) return `${pathname}:${params.get('discovery')}`
  return null
}

/** Restore both browser-back and the explicit results link, including async mounts. */
export function DiscoveryNavigationMemory() {
  const { pathname, search } = useLocation()
  const key = workspaceKey(pathname, search)
  const previousPath = useRef(pathname)
  useLayoutEffect(() => {
    const changedPage = previousPath.current !== pathname
    previousPath.current = pathname
    if (!key) return
    const saved = positions.get(key)
    let frame = 0
    let restoring = !!saved && changedPage
    const restore = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        if (!saved) return
        window.scrollTo(0, saved.y)
        if (saved.focus) document.getElementById(saved.focus)?.focus({ preventScroll: true })
      })
    }
    const observer = new MutationObserver(() => { if (restoring) restore() })
    if (restoring) {
      restore()
      observer.observe(document.body, { childList: true, subtree: true })
    } else if (changedPage) window.scrollTo(0, 0)
    const remember = () => {
      if (!restoring) positions.set(key, { y: window.scrollY, focus: document.activeElement?.id ?? '' })
    }
    const stop = () => { restoring = false; observer.disconnect(); cancelAnimationFrame(frame) }
    const timer = window.setTimeout(stop, 3000)
    window.addEventListener('scroll', remember, { passive: true })
    window.addEventListener('focusin', remember)
    window.addEventListener('wheel', stop, { once: true })
    window.addEventListener('pointerdown', stop, { once: true })
    window.addEventListener('keydown', stop, { once: true })
    return () => {
      remember(); stop(); clearTimeout(timer)
      window.removeEventListener('scroll', remember)
      window.removeEventListener('focusin', remember)
      window.removeEventListener('wheel', stop)
      window.removeEventListener('pointerdown', stop)
      window.removeEventListener('keydown', stop)
    }
  }, [key, pathname])
  return null
}
