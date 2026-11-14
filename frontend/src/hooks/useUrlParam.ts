import { useSearchParams } from "react-router-dom"

/** URL 쿼리 값 하나(보기·탭 상태의 단일 소스) — 기본값이면 지우고, 기록을 쌓지 않으며 스크롤을 그대로 둔다 */
export function useUrlParam(key: string, dflt: string) {
  const [params, setParams] = useSearchParams()
  const value = params.get(key) ?? dflt
  const set = (v: string) => setParams(prev => {
    const n = new URLSearchParams(prev)
    if (v === dflt) n.delete(key); else n.set(key, v)
    return n
  }, { replace: true, preventScrollReset: true })
  return [value, set] as const
}
