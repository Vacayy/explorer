import { Link, NavLink, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { useTheme } from "next-themes"
import { Archive, Moon, PanelLeft, PanelRight, Rss, Search, Settings, SlidersHorizontal, Sun } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Kbd } from "@/components/ui/kbd"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useSidebar } from "@/components/ui/sidebar"
import { cn } from "@/lib/utils"
import { openOmnibar } from "@/lib/omnibar"
import { SECTIONS, locate } from "./navConfig"
import { ApprovalsInbox, SavedInbox } from "./Inboxes"
import { ShellButton } from "./ShellButton"

interface HealthItem { key: string; label: string; status: string; detail: string }

/**
 * 상단 바 — 내 목록 토글 · 로고 · L1 5탭 · 검색 · 운영 상태 · 인박스 · 설정 · AI 대화 토글 (docs/specs/app-shell.md §3).
 * L1 활성은 navConfig.locate 단일 판정. 도시에·대화 등 L1 밖 화면에서는 어느 탭도 활성이 아니다.
 */
export function TopBar({ aiOpen, onToggleAi }: { aiOpen: boolean; onToggleAi: () => void }) {
  const { pathname, search } = useLocation()
  const here = locate(pathname, search)
  const { open, openMobile, isMobile, toggleSidebar } = useSidebar()

  // <768: 가운데 5탭은 하단 TabBar로 내려가고 위에는 아이콘만 남는다 (app-shell.md §6)
  return (
    <header className="sticky top-0 z-30 flex h-(--topbar-height) items-center justify-between border-b bg-background px-2 md:grid md:grid-cols-[1fr_auto_1fr] md:px-3">
      <div className="flex min-w-0 items-center gap-2">
        <ShellButton icon={PanelLeft} label="내 목록 (⌘B)" pressed={isMobile ? openMobile : open} onClick={toggleSidebar} />
        <Link to="/home" className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <span aria-hidden className="grid size-[22px] place-items-center rounded-md bg-foreground text-[11px] font-bold text-background">E</span>
          <span className="md:max-lg:sr-only">Explorer</span>
        </Link>
      </div>

      <nav aria-label="메인" className="hidden h-full items-stretch md:flex">
        {SECTIONS.map((s, i) => {
          const active = here?.section === s.key
          return (
            <NavLink key={s.key} to={s.path} aria-current={active ? "page" : undefined} title={`⌥${i + 1}`}
              className={cn(
                "flex items-center border-b-2 px-2.5 text-sm transition-colors lg:px-3.5",
                active ? "border-foreground font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}>
              {s.label}
            </NavLink>
          )
        })}
      </nav>

      <div className="flex min-w-0 items-center justify-end gap-0.5 md:gap-1">
        <Button variant="outline" size="sm" onClick={openOmnibar} data-search-input
          className="mr-1 hidden h-8 w-52 justify-start gap-2 bg-muted/40 font-normal text-muted-foreground xl:flex">
          <Search className="size-3.5" aria-hidden />종목·문서·서사 검색<Kbd className="ml-auto">⌘K</Kbd>
        </Button>
        <ShellButton icon={Search} label="검색 (⌘K)" onClick={openOmnibar} className="xl:hidden" />
        <HealthDot />
        <ApprovalsInbox />
        <SavedInbox />
        <SettingsMenu />
        <ShellButton icon={PanelRight} label="AI 대화 (⌘J)" pressed={aiOpen} onClick={onToggleAi} />
      </div>
    </header>
  )
}

/** 운영 상태 — 결과 데이터 신선도(D-222). 전부 최신이면 초록, 지연·오류가 있으면 주황 + 개수 → 관리자 */
function HealthDot() {
  const { data, isError } = useQuery(
    apiQuery<HealthItem[]>({ key: ["spine", "admin", "health"], url: "/api/spine/admin/health", staleTime: STALE.short }),
  )
  const bad = (data ?? []).filter(h => h.status !== "ok")
  const label = isError ? "운영 상태를 불러오지 못했습니다" : !data ? "운영 상태 확인 중"
    : bad.length ? `지연·오류 ${bad.length}건: ${bad.slice(0, 3).map(h => h.label).join(", ")}${bad.length > 3 ? " …" : ""}` : `원천 ${data.length}개 모두 최신`
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link to="/admin" aria-label={`운영 상태 — ${label}`}
          className="hidden h-7 items-center gap-1.5 rounded-full md:flex border px-2.5 text-xs text-muted-foreground hover:text-foreground">
          <span aria-hidden className={cn("size-[7px] rounded-full", isError || bad.length ? "bg-chart-warning" : data ? "bg-chart-green" : "bg-muted-foreground/40")} />
          {data ? (bad.length ? `운영 ${data.length - bad.length}/${data.length}` : "운영") : "운영"}
        </Link>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

/** 설정 — 드물게 쓰는 것: 테마 · 소스 관리 · 관리자 · 보관함 */
function SettingsMenu() {
  const { resolvedTheme, setTheme } = useTheme()
  const dark = resolvedTheme === "dark"
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <ShellButton icon={Settings} label="설정" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-44">
        <DropdownMenuItem onSelect={() => setTheme(dark ? "light" : "dark")}>
          {dark ? <Sun /> : <Moon />} {dark ? "라이트 모드" : "다크 모드"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild><Link to="/sources"><Rss /> 소스 관리</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/admin"><SlidersHorizontal /> 관리자</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/archive"><Archive /> 보관함</Link></DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
