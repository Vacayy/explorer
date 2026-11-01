import { useSearchParams } from 'react-router-dom'

/** /home의 보기 — URL만이 상태 소스. 시장은 홈 › 대시보드, 피드(home_view=feed)는 캔버스 › 피드 (docs/specs/app-shell.md §2) */
export function getHomeMode(search: string): 'market' | 'feed' {
  return new URLSearchParams(search).get('home_view') === 'feed' ? 'feed' : 'market'
}

export function useHomeMode() {
  const [params] = useSearchParams()
  return getHomeMode(params.toString())
}
