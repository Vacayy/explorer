import { Link } from "react-router-dom"
import { Archive, PanelRight, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { useSidebar } from "@/components/ui/sidebar"
import ThemeToggle from "@/components/shared/ThemeToggle"

/**
 * 헤더 — 로고 + 단일 검색 진입(옴니바 트리거) + 유틸 아이콘.
 * 검색·이동·질문은 전부 옴니바(⌘K)로 수렴 — 헤더는 진입점만 제공한다.
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
