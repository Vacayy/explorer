import { useState } from "react"
import { Link } from "react-router-dom"
import { ChevronRight, FileText } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { useExplorerOutputs } from "@/hooks/useTimeline"
import { SYSTEM_KIND_LABEL } from "@/lib/canvas"
import { formatRelativeTime } from "@/utils/format"
import { ShellButton } from "./ShellButton"

/** 마지막으로 연 시각 — 이 뒤에 만든 산출물이 있으면 점을 단다. 브라우저 저장소가 막혀 있으면 점 없이 둔다 */
const SEEN_KEY = "explorer.aiOutputs.seenAt"
function readSeen(): string | null {
  try { return localStorage.getItem(SEEN_KEY) } catch { return null }
}
function writeSeen(iso: string) {
  try { localStorage.setItem(SEEN_KEY, iso) } catch { /* private storage */ }
}

/** 새 산출물 점 — 한 번도 열지 않았으면 산출물이 하나라도 있을 때, 열었으면 그 뒤에 만든 것이 있을 때 */
export function useAiOutputs() {
  const q = useExplorerOutputs()
  const [seen, setSeen] = useState(readSeen)
  const items = q.data?.items ?? []
  const latest = items[0]?.occurred_at
  const fresh = !!latest && (!seen || new Date(latest).getTime() > new Date(seen).getTime())
  const markSeen = () => { const now = new Date().toISOString(); writeSeen(now); setSeen(now) }
  return { q, items, fresh, markSeen }
}

const TITLE = "AI가 최근 만든 것"

/** 목록 — 종류 · 제목 · 시각, 줄을 누르면 산출물 화면. 높이 상한 안에서 스크롤 */
function OutputList({ q, items, onNavigate, className }: { q: ReturnType<typeof useExplorerOutputs>; items: NonNullable<ReturnType<typeof useExplorerOutputs>["data"]>["items"]; onNavigate: () => void; className: string }) {
  if (q.isLoading) return <div role="status" aria-label="불러오는 중" className="space-y-2 px-4 py-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div>
  if (q.isError && !q.data) return <div className="flex items-center gap-3 px-4 py-4 text-sm text-ink-2">
    <span>목록을 불러오지 못했습니다.</span><Button variant="outline" size="sm" onClick={() => void q.refetch()}>다시 시도</Button>
  </div>
  if (items.length === 0) return <p className="px-4 py-4 text-sm text-ink-2">아직 만든 산출물이 없습니다.</p>
  return <ul data-ai-outputs className={className}>
    {items.map(item => <li key={item.id} className="border-t first:border-t-0">
      <Link to={item.to} onClick={onNavigate} className="flex items-center gap-2.5 px-4 py-2 hover:bg-chip focus-visible:bg-chip focus-visible:outline-none">
        <Badge variant="neutral" className="w-[68px] shrink-0 justify-center">{SYSTEM_KIND_LABEL[item.kind] ?? item.kind}</Badge>
        <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{item.title}</span>
        <time dateTime={item.occurred_at} title={item.occurred_at} className="shrink-0 font-mono text-xs text-ink-3 tabular-nums">{formatRelativeTime(item.occurred_at)}</time>
      </Link>
    </li>)}
  </ul>
}

function Footer({ onNavigate }: { onNavigate: () => void }) {
  return <div className="flex justify-end border-t px-4 py-2.5">
    <Link to="/feed?channel_type=system" onClick={onNavigate} className="flex items-center gap-0.5 text-[13px] font-medium text-ink hover:opacity-75">
      Explorer 산출물 전체<ChevronRight className="size-3.5" aria-hidden />
    </Link>
  </div>
}

/**
 * 상단 바 'AI가 최근 만든 것'(D-325, ia-redesign §4.11) — 넓은 화면은 인박스 옆 아이콘 + Popover.
 * 옛 홈 피드 카드(AiActivityFeed, 4a에서 빠짐)를 셸로 옮겼다. 원천은 피드 Explorer 묶음과 같은 타임라인(scope=system).
 */
export function AiOutputsButton({ className }: { className?: string }) {
  const [open, setOpen] = useState(false)
  const { q, items, fresh, markSeen } = useAiOutputs()
  return (
    <Popover open={open} onOpenChange={v => { setOpen(v); if (v) markSeen() }}>
      <PopoverTrigger asChild>
        <ShellButton icon={FileText} label={TITLE} dot={fresh} className={className} aria-label={fresh ? `${TITLE} — 새 산출물 있음` : TITLE} />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[420px] max-w-[calc(100vw-2rem)] gap-0 overflow-hidden p-0">
        <div className="px-4 pt-3.5 pb-2.5 text-base font-semibold">{TITLE}</div>
        <div className="border-t">
          <OutputList q={q} items={items} onNavigate={() => setOpen(false)} className="max-h-[min(60vh,480px)] overflow-y-auto overscroll-contain" />
        </div>
        <Footer onNavigate={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  )
}

/**
 * 폰 로고 메뉴(D-322) — 메뉴 시트의 줄 + 아래 시트 목록. 줄을 누르면 메뉴 시트가 닫히므로 목록 시트는 메뉴 밖(PhoneMenu)에 둔다.
 * 쓰는 쪽: const ai = useAiOutputs() → <AiOutputsRow ai={ai} …/> · <AiOutputsSheet ai={ai} …/>
 */
export function AiOutputsRow({ ai, className, onClick }: { ai: ReturnType<typeof useAiOutputs>; className: string; onClick: () => void }) {
  return <Button variant="ghost" className={className} onClick={() => { ai.markSeen(); onClick() }}>
    <FileText className="size-[18px] text-ink-2" aria-hidden />{TITLE}
    {ai.fresh && <span aria-label="새 산출물 있음" role="img" className="ml-auto size-[7px] rounded-full bg-hyp" />}
  </Button>
}

export function AiOutputsSheet({ ai, open, onOpenChange }: { ai: ReturnType<typeof useAiOutputs>; open: boolean; onOpenChange: (open: boolean) => void }) {
  return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent side="bottom" className="max-h-[80dvh] gap-0 pb-[env(safe-area-inset-bottom)]">
      <SheetHeader className="pb-2"><SheetTitle>{TITLE}</SheetTitle></SheetHeader>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain border-t">
        <OutputList q={ai.q} items={ai.items} onNavigate={() => onOpenChange(false)} className="" />
      </div>
      <Footer onNavigate={() => onOpenChange(false)} />
    </SheetContent>
  </Sheet>
}
