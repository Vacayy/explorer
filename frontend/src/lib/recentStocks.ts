/** 옴니바 빈 상태의 "최근 본 종목" — 이 브라우저에만 남는 편의 기록(localStorage). D-189. */
export interface RecentStock { code: string; name: string; market: 'kr' | 'us'; at: number }

const KEY = 'explorer.recent-stocks'
const LIMIT = 8

export function readRecentStocks(): RecentStock[] {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter(item => item && typeof item.code === 'string' && typeof item.name === 'string') : []
  } catch { return [] }
}

export function rememberRecentStock(entry: Omit<RecentStock, 'at'>): void {
  try {
    const rest = readRecentStocks().filter(item => !(item.code === entry.code && item.market === entry.market))
    localStorage.setItem(KEY, JSON.stringify([{ ...entry, at: Date.now() }, ...rest].slice(0, LIMIT)))
  } catch { /* 저장 불가 환경에서는 조용히 건너뛴다(편의 기능). */ }
}
