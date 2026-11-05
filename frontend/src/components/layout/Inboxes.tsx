import { useState } from "react"
import { Link } from "react-router-dom"
import { Bookmark, Inbox } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import ApprovalsCard from "@/components/home/ApprovalsCard"
import { BriefingList } from "@/components/home/BriefingList"
import { useHome } from "@/hooks/useHome"
import { useSaved } from "@/hooks/useSaved"
import { ShellButton } from "./ShellButton"

/**
 * 승인 인박스 — 대기 건수 배지 + 클릭 시 Sheet(ApprovalsCard 재활용). "어느 화면에서든"(D-056)은 상단 바 상시 배지로 유지.
 * count 쿼리는 ApprovalsCard와 같은 queryKey라 캐시를 공유한다.
 */
export function useApprovalsCount() {
  const { data: items = [] } = useQuery(
    apiQuery<{ id: number }[]>({ key: ["spine", "approvals"], url: "/api/spine/approvals", staleTime: STALE.short }),
  )
  return items.length
}

export function ApprovalsInbox({ className }: { className?: string }) {
  const [open, setOpen] = useState(false)
  const count = useApprovalsCount()

  return (
    <>
      <ShellButton icon={Inbox} label="인박스 · 승인 대기 · 저장됨" dot={count > 0} onClick={() => setOpen(true)} aria-label={count ? `인박스 — 승인 대기 ${count}건` : "인박스"} className={className} />
      <InboxSheet open={open} onOpenChange={setOpen} count={count} />
    </>
  )
}

/** 인박스 창 — 상단 바 아이콘(데스크톱)과 폰 로고 메뉴(D-322)가 같이 쓴다 */
export function InboxSheet({ open, onOpenChange, count }: { open: boolean; onOpenChange: (open: boolean) => void; count: number }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto">
        <SheetHeader className="flex-row items-center justify-between gap-2 pr-12">
          <SheetTitle>인박스</SheetTitle>
          <SavedLink onNavigate={() => onOpenChange(false)} />
        </SheetHeader>
        {open && <InboxBody count={count} />}
      </SheetContent>
    </Sheet>
  )
}

/** 저장됨 — 상단 바 아이콘 대신 인박스 머리의 링크(D-323) */
function SavedLink({ onNavigate }: { onNavigate: () => void }) {
  const count = useSaved().data?.length ?? 0
  return <Link to="/feed/saved" onClick={onNavigate} className="flex items-center gap-1 text-[13px] text-ink-2 hover:text-ink">
    <Bookmark className="size-3.5" aria-hidden />저장됨{count > 0 && <span className="font-mono tabular-nums text-ink-3">{count}</span>} ›
  </Link>
}

/** 인박스 본문 — 공지(브리핑) + 승인 대기. Sheet 열릴 때만 마운트(홈 payload 지연 로드). */
function InboxBody({ count }: { count: number }) {
  const { data } = useHome()
  const briefing = data?.briefing ?? []
  return (
    <div className="px-4 pb-6 space-y-5">
      {briefing.length > 0 && (
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-1.5">공지사항</div>
          <BriefingList items={briefing} />
        </div>
      )}
      <div>
        <div className="text-xs font-medium text-muted-foreground mb-1.5">승인 대기 {count > 0 ? `(${count})` : ""}</div>
        {count === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">대기 중인 제안이 없습니다.</p>
        ) : (
          <ApprovalsCard hideHeader />
        )}
      </div>
    </div>
  )
}
