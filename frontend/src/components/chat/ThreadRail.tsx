import { useMemo, useState } from "react"
import { Plus, Search, Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import type { ConversationItem } from "@/types"
import { formatKstSlashDate, formatNumber } from "@/utils/format"
import { cn } from "@/lib/utils"

interface Props {
  threads: ConversationItem[]
  loading: boolean
  error: boolean
  activeId: number | null
  onSelect: (id: number) => void
  onNew: () => void
}

/**
 * 대화 목록 (시안 Chat, ia-redesign §4.14) — 머리('대화' · 새 대화) · 대화 검색 · 최근순 목록(제목 + 'MM/DD · 메시지 n').
 * 데스크톱 왼쪽 칸, 폰·태블릿 Sheet, AI 패널 Popover가 같은 컴포넌트를 쓴다.
 * 웹·텔레그램 공용 풀(텔레그램 스레드는 아이콘으로 표시). 이름 변경은 대화 머리 제목에서, 삭제는 API가 없어 없음.
 */
export function ThreadRail({ threads, loading, error, activeId, onSelect, onNew }: Props) {
  const [q, setQ] = useState("")
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return needle ? threads.filter((t) => (t.title ?? "").toLowerCase().includes(needle)) : threads
  }, [threads, q])

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 px-3 pt-3 pb-2">
        <div className="flex items-center justify-between gap-2 pl-1">
          <h2 className="text-[15px] font-semibold">대화</h2>
          <Button variant="outline" size="sm" className="rounded-full" onClick={onNew}>
            <Plus className="size-3.5" aria-hidden /> 새 대화
          </Button>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="대화 검색"
            className="h-8 pl-8 text-[13px]" aria-label="대화 검색" />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {loading && (
          <div className="space-y-2 px-2 pt-2">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}
          </div>
        )}
        {error && !loading && (
          <p className="px-2 pt-3 text-xs text-destructive">대화 목록을 불러오지 못했습니다.</p>
        )}
        {!loading && !error && threads.length === 0 && (
          <p className="px-2 pt-3 text-xs text-muted-foreground">아직 대화가 없습니다.</p>
        )}
        {!loading && threads.length > 0 && list.length === 0 && (
          <p className="px-2 pt-3 text-xs text-muted-foreground">"{q}"에 해당하는 대화가 없습니다.</p>
        )}
        <ul className="space-y-px">
          {list.map((t) => {
            const active = t.id === activeId
            return (
              <li key={t.id}>
                <Button
                  variant="ghost"
                  onClick={() => onSelect(t.id)}
                  aria-current={active ? "page" : undefined}
                  data-thread={t.id}
                  className={cn(
                    "h-auto w-full flex-col items-start gap-0.5 rounded-lg px-2.5 py-2 text-left font-normal whitespace-normal",
                    active ? "bg-muted font-medium hover:bg-muted" : "text-foreground/90",
                  )}
                >
                  <span className="line-clamp-2 w-full text-[13px] leading-5">{t.title || "(제목 없음)"}</span>
                  <span className="flex items-center gap-1 text-[11px] font-normal tabular-nums text-muted-foreground">
                    {t.channel === "telegram" && <Send className="size-3" aria-label="텔레그램" />}
                    {formatKstSlashDate(t.updated_at, false)} · 메시지 {formatNumber(t.message_count)}
                  </span>
                </Button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
