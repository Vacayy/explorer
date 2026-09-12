import { useMemo, useState } from "react"
import { MessageSquare, Search, Send, SquarePen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { utcMs } from "@/hooks/useChat"
import type { ConversationItem } from "@/types"
import { formatRelativeTime } from "@/utils/format"
import { cn } from "@/lib/utils"

interface Props {
  threads: ConversationItem[]
  loading: boolean
  error: boolean
  activeId: number | null
  onSelect: (id: number) => void
  onNew: () => void
}

type Group = "오늘" | "어제" | "지난 7일" | "이전"

function groupOf(updatedAt: string): Group {
  const d = new Date()
  const startToday = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const t = utcMs(updatedAt)
  if (t >= startToday) return "오늘"
  if (t >= startToday - 86_400_000) return "어제"
  if (t >= startToday - 6 * 86_400_000) return "지난 7일"
  return "이전"
}

const GROUP_ORDER: Group[] = ["오늘", "어제", "지난 7일", "이전"]

/**
 * 스레드 레일 — 새 대화 · 검색 · 날짜 그룹 목록. 데스크톱 aside와 모바일 Sheet가 같은 컴포넌트를 렌더한다.
 * 웹·텔레그램 공용 풀(텔레그램 스레드는 아이콘으로 표시). 이름 변경·삭제는 API 부재로 없음(spec §7).
 */
export function ThreadRail({ threads, loading, error, activeId, onSelect, onNew }: Props) {
  const [q, setQ] = useState("")
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const list = needle ? threads.filter((t) => (t.title ?? "").toLowerCase().includes(needle)) : threads
    const by = new Map<Group, ConversationItem[]>()
    for (const t of list) {
      const g = groupOf(t.updated_at)
      by.set(g, [...(by.get(g) ?? []), t])
    }
    return GROUP_ORDER.filter((g) => by.has(g)).map((g) => [g, by.get(g)!] as const)
  }, [threads, q])

  return (
    <div className="flex h-full flex-col">
      <div className="px-3 pt-3 pb-2 space-y-2">
        <Button variant="outline" className="w-full justify-start gap-2 rounded-xl h-9" onClick={onNew}>
          <SquarePen className="size-4" /> 새 대화
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="대화 검색"
            className="h-8 rounded-xl pl-8 text-[13px]" aria-label="대화 검색" />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {loading && (
          <div className="space-y-2 px-2 pt-2">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-8 w-full rounded-lg" />)}
          </div>
        )}
        {error && !loading && (
          <p className="px-2 pt-3 text-xs text-destructive">대화 목록을 불러올 수 없습니다.</p>
        )}
        {!loading && !error && threads.length === 0 && (
          <p className="px-2 pt-3 text-xs leading-relaxed text-muted-foreground">
            아직 대화가 없습니다. 첫 질문을 해보세요 — 텔레그램 봇 문답도 여기 쌓입니다.
          </p>
        )}
        {!loading && threads.length > 0 && groups.length === 0 && (
          <p className="px-2 pt-3 text-xs text-muted-foreground">"{q}"에 해당하는 대화가 없습니다.</p>
        )}
        {groups.map(([g, items]) => (
          <section key={g} className="pt-3 first:pt-1">
            <h3 className="px-2 pb-1 text-[11px] font-medium text-muted-foreground">{g}</h3>
            <ul className="space-y-px">
              {items.map((t) => {
                const active = t.id === activeId
                return (
                  <li key={t.id}>
                    <Button
                      variant="ghost"
                      onClick={() => onSelect(t.id)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group/thread h-auto w-full justify-start gap-2 rounded-lg px-2 py-1.5 text-left font-normal whitespace-normal",
                        active ? "bg-accent text-accent-foreground hover:bg-accent" : "text-foreground/90",
                      )}
                    >
                      {t.channel === "telegram"
                        ? <Send className="size-3.5 shrink-0 text-muted-foreground" aria-label="텔레그램" />
                        : <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />}
                      <span className="min-w-0 flex-1 truncate text-[13px] leading-5">{t.title || "(제목 없음)"}</span>
                      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                        {formatRelativeTime(new Date(utcMs(t.updated_at)).toISOString())}
                      </span>
                    </Button>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
