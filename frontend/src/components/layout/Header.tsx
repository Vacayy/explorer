import { useState } from "react"
import { Link } from "react-router-dom"
import { Archive, Inbox, PanelRight, Search, SlidersHorizontal } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Button } from "@/components/ui/button"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { useSidebar } from "@/components/ui/sidebar"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet"
import ThemeToggle from "@/components/shared/ThemeToggle"
import ApprovalsCard from "@/components/home/ApprovalsCard"
import { BriefingList } from "@/components/home/BriefingList"
import { useHome } from "@/hooks/useHome"

/**
 * 헤더 — 로고 + 단일 검색 진입(옴니바 트리거) + 유틸 아이콘.
 * 검색·이동·질문은 전부 옴니바(⌘K)로 수렴 — 헤더는 진입점만 제공한다.
 * 승인 대기는 상시 배지(어느 화면에서든) — 클릭 시 인박스 Sheet (홈에서 격상).
 */
function openOmnibar() {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
}

export default function Header() {
  const { toggleSidebar } = useSidebar()
  return (
    <header className="sticky top-0 z-50 bg-card">
      <div className="mx-auto max-w-[var(--layout-shell)] flex items-center gap-4 px-6 h-14">
        <Link to="/home" className="text-[15px] font-bold tracking-tight whitespace-nowrap">
          Stock Explorer
        </Link>

        <button
          type="button"
          onClick={openOmnibar}
          data-search-input
          className="group flex flex-1 max-w-[420px] items-center gap-2 h-9 rounded-lg bg-secondary px-3 text-[13px] text-muted-foreground transition-colors hover:bg-secondary/70"
        >
          <Search className="h-4 w-4 shrink-0" />
          <span className="truncate">기업·종목 검색, 이동, 질문</span>
          <KbdGroup className="ml-auto shrink-0">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
          </KbdGroup>
        </button>

        <div className="ml-auto flex items-center gap-1">
          <ApprovalsInbox />
          <Button variant="ghost" size="icon-sm" asChild>
            <Link to="/admin" title="관리자 — cron 작업·기능 on/off">
              <SlidersHorizontal className="h-4 w-4" />
            </Link>
          </Button>
          <Button variant="ghost" size="icon-sm" asChild>
            <Link to="/archive" title="보관함 — 안 쓰는 화면 모음">
              <Archive className="h-4 w-4" />
            </Link>
          </Button>
          <ThemeToggle />
          <Button variant="ghost" size="icon-sm" onClick={toggleSidebar}
            title="팔로우 레일 토글" aria-label="팔로우 레일 토글">
            <PanelRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </header>
  )
}

/**
 * 승인 인박스 — 대기 건수 배지 + 클릭 시 Sheet(ApprovalsCard 재활용).
 * count 쿼리는 ApprovalsCard와 같은 queryKey라 캐시를 공유한다.
 */
function ApprovalsInbox() {
  const [open, setOpen] = useState(false)
  const { data: items = [] } = useQuery(
    apiQuery<{ id: number }[]>({ key: ["spine", "approvals"], url: "/api/spine/approvals", staleTime: STALE.short }),
  )
  const count = items.length

  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => setOpen(true)}
        title="승인 대기 — 기계의 제안, 결정은 사람이"
        aria-label={`승인 대기 ${count}건`}
        className="relative"
      >
        <Inbox className="h-4 w-4" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-hypothesis px-1 text-[10px] font-semibold leading-none text-white tabular-nums">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </Button>
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
