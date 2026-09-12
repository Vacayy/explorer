import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

export function getHomeMode(search: string) {
  const explicit = new URLSearchParams(search).get('home_view')
  if (explicit) return explicit === 'feed' ? 'feed' : 'market'
  try { return localStorage.getItem('explorer.home.mode') === 'feed' ? 'feed' : 'market' }
  catch { return 'market' }
}

export function useHomeMode() {
  const [params, setParams] = useSearchParams()
  const mode = getHomeMode(params.toString())
  useEffect(() => { try { localStorage.setItem('explorer.home.mode', mode) } catch { /* private storage */ } }, [mode])
  return { mode, setMode: (value: string) => {
    try { localStorage.setItem('explorer.home.mode', value) } catch { /* private storage */ }
    setParams(prev => {
      const next = new URLSearchParams(prev); next.set('home_view', value); return next
    })
  } }
}
