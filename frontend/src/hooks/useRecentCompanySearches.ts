import { useState } from 'react'
import type { Company, RecentCompanySearch } from '@/types'

const KEY = 'explorer.recent-company-searches.v1'
const LIMIT = 8

function readHistory(): RecentCompanySearch[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    if (!Array.isArray(parsed)) return []
    const entries: RecentCompanySearch[] = []
    for (const item of parsed) {
      if (!item || typeof item.stock_code !== 'string' || !/^[0-9A-Z]{6}$/.test(item.stock_code)
        || typeof item.corp_name !== 'string' || !item.corp_name.trim()
        || entries.some(entry => entry.stock_code === item.stock_code)) continue
      entries.push({ stock_code: item.stock_code, corp_name: item.corp_name.trim() })
      if (entries.length === LIMIT) break
    }
    return entries
  } catch { return [] }
}

/** Actual selections in the discovery picker; separate from the omnibar's viewed stocks. */
export function useRecentCompanySearches() {
  const [recent, setRecent] = useState(readHistory)
  const [stored, setStored] = useState(true)

  function update(next: RecentCompanySearch[]) {
    setRecent(next)
    try {
      if (next.length) localStorage.setItem(KEY, JSON.stringify(next))
      else localStorage.removeItem(KEY)
      setStored(true)
    } catch { setStored(false) }
  }

  function remember(company: Pick<Company, 'corp_name' | 'stock_code'>) {
    if (!company.stock_code || !company.corp_name.trim()) return
    update([
      { stock_code: company.stock_code, corp_name: company.corp_name },
      ...recent.filter(item => item.stock_code !== company.stock_code),
    ].slice(0, LIMIT))
  }

  return { recent, stored, remember, clear: () => update([]) }
}
