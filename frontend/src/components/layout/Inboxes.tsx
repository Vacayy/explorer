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
import SavedList from "@/components/follow/SavedList"
import { EmptyState } from "@/components/shared/ErrorState"
import { DockItem } from "./DockItem"

/**
 * 저장됨 인박스 — 저장 건수 배지 + 클릭 시 Sheet(SavedList compact). (D-077)
 * 목록 쿼리는 SavedPage·SaveButton과 같은 queryKey라 캐시 공유. 헤더에서 도크로 이동(D-136).
 */
export function SavedInbox({ compact }: { compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const { data: items = [] } = useSaved()
  const count = items.length

  return (
    <>
      <DockItem icon={Bookmark} label="저장" badge={count} onClick={() => setOpen(true)}
        aria-label={`저장됨 ${count}건`} className={compact ? "w-full" : undefined} />
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto">
          <SheetHeader>
            <SheetTitle>저장됨</SheetTitle>
          </SheetHeader>
          <div className="px-4 pb-6">
            {count === 0 ? (
              <EmptyState message="아직 저장한 항목이 없어요." />
            ) : (
              <>
                <SavedList items={items} compact onNavigate={() => setOpen(false)} />
                <Link
                  to="/follow/saved"
                  onClick={() => setOpen(false)}
                  className="mt-3 block text-center text-xs text-muted-foreground hover:underline"
                >
                  전체 보기
                </Link>
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}

/**
 * 승인 인박스 — 대기 건수 배지 + 클릭 시 Sheet(ApprovalsCard 재활용). "어느 화면에서든"(D-056)은 도크 상시 배지로 유지.
 * count 쿼리는 ApprovalsCard와 같은 queryKey라 캐시를 공유한다.
 */
export function ApprovalsInbox({ compact }: { compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const { data: items = [] } = useQuery(
    apiQuery<{ id: number }[]>({ key: ["spine", "approvals"], url: "/api/spine/approvals", staleTime: STALE.short }),
  )
  const count = items.length

  return (
    <>
      <DockItem icon={Inbox} label="승인" badge={count} badgeTone="hypothesis" onClick={() => setOpen(true)}
        aria-label={`승인 대기 ${count}건`} className={compact ? "w-full" : undefined} />
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto">
          <SheetHeader>
            <SheetTitle>인박스</SheetTitle>
          </SheetHeader>
          {open && <InboxBody count={count} />}
        </SheetContent>
      </Sheet>
    </>
  )
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
