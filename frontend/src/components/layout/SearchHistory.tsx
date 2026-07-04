import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { cn } from "@/lib/utils"

const STORAGE_KEY = "stock-explorer-history"
const MAX_HISTORY = 30

export interface HistoryEntry {
  stock_code: string
  corp_name: string
  corp_code: string
  visited_at: string
}

function loadHistory(): HistoryEntry[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]")
  } catch {
    return []
  }
}

function saveHistory(entries: HistoryEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY)))
}

export function addToHistory(company: Company) {
  const entries = loadHistory().filter((e) => e.stock_code !== company.stock_code)
  entries.unshift({
    stock_code: company.stock_code!,
    corp_name: company.corp_name,
    corp_code: company.corp_code,
    visited_at: new Date().toISOString(),
  })
  saveHistory(entries)
}

interface Props {
  currentStockCode: string | null
}

export default function SearchHistory({ currentStockCode }: Props) {
  const navigate = useNavigate()
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    setHistory(loadHistory())
  }, [currentStockCode])

  const handleClear = () => {
    localStorage.removeItem(STORAGE_KEY)
    setHistory([])
  }

  const handleRemove = (stockCode: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const updated = history.filter((h) => h.stock_code !== stockCode)
    saveHistory(updated)
    setHistory(updated)
  }

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="fixed right-0 top-[120px] w-8 h-20 bg-card border border-r-0 rounded-l-lg flex items-center justify-center cursor-pointer shadow-sm text-xs text-muted-foreground"
        style={{ writingMode: "vertical-rl" }}
      >
        히스토리
      </button>
    )
  }

  return (
    <aside className="w-[220px] shrink-0 bg-card border-l sticky top-[110px] h-[calc(100vh-110px)] overflow-y-auto py-4">
      <div className="flex items-center justify-between px-3.5 mb-3">
        <h3 className="text-xs font-semibold text-secondary-foreground">검색 히스토리</h3>
        <div className="flex gap-2 items-center">
          {history.length > 0 && (
            <button onClick={handleClear} className="text-[11px] text-muted-foreground hover:text-foreground cursor-pointer">
              전체삭제
            </button>
          )}
          <button onClick={() => setCollapsed(true)} className="text-muted-foreground hover:text-foreground cursor-pointer text-sm leading-none">
            ✕
          </button>
        </div>
      </div>

      {history.length === 0 && (
        <p className="px-3.5 py-8 text-xs text-muted-foreground text-center">검색 기록이 없습니다.</p>
      )}

      {history.map((entry) => {
        const isActive = entry.stock_code === currentStockCode
        return (
          <div
            key={entry.stock_code}
            onClick={() => navigate(`/analyze/${entry.stock_code}/summary`)}
            className={cn(
              "flex items-center justify-between px-3.5 py-2.5 cursor-pointer border-l-[3px] transition-colors",
              isActive
                ? "bg-accent border-l-primary"
                : "border-l-transparent hover:bg-muted/50"
            )}
          >
            <div className="min-w-0">
              <div className={cn(
                "text-[13px] truncate",
                isActive ? "font-semibold text-primary" : "text-foreground"
              )}>
                {entry.corp_name}
              </div>
              <div className="text-[11px] text-muted-foreground">{entry.stock_code}</div>
            </div>
            <button
              onClick={(e) => handleRemove(entry.stock_code, e)}
              className="text-xs text-muted-foreground/40 hover:text-muted-foreground shrink-0 ml-1 cursor-pointer"
            >
              ✕
            </button>
          </div>
        )
      })}
    </aside>
  )
}
