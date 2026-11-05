import { Link, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { useTheme } from "next-themes"
import { Archive, ChevronRight, Globe, Monitor, Moon, Rss, Search, Settings, SlidersHorizontal, Sparkles, Sun } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Kbd } from "@/components/ui/kbd"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { openOmnibar } from "@/lib/omnibar"
import { SECTIONS, locate } from "./navConfig"
import { ApprovalsInbox, SavedInbox } from "./Inboxes"
import { ShellButton } from "./ShellButton"

interface HealthItem { key: string; label: string; status: string; detail: string; critical?: boolean }
const STATUS_LABEL: Record<string, string> = { stale: "지연", error: "오류" }

/**
 * 상단 바 — 로고 · L1 6탭(활성·aria-current 모두 locate 판정 — NavLink는 쿼리를 보지 않아 쓰지 않는다) · 검색 · 운영 상태 · 인박스 · 설정 · AI 대화 토글 (docs/specs/app-shell.md §3).
 * L1 활성은 navConfig.locate 단일 판정. 도시에·대화 등 L1 밖 화면에서는 어느 탭도 활성이 아니다.
 */
export function TopBar({ aiOpen, onToggleAi }: { aiOpen: boolean; onToggleAi: () => void }) {
  const { pathname, search } = useLocation()
  const here = locate(pathname, search)

  // <768: 가운데 6탭은 하단 TabBar로 내려가고 위에는 아이콘만 남는다 (app-shell.md §6)
  return (
    <header className="sticky top-0 z-30 flex h-(--topbar-height) items-center justify-between gap-3 border-b bg-background px-2 md:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <Link to="/home" className="flex shrink-0 items-center gap-2 font-display text-[17px] font-medium tracking-[-0.01em]">
          <Globe className="size-[18px]" aria-hidden />
          <span className="md:max-lg:sr-only">Explorer</span>
        </Link>
        <nav aria-label="메인" className="hidden items-center gap-0.5 md:flex">
          {SECTIONS.map((s, i) => {
            const active = here?.section === s.key
            return (
              <Link key={s.key} to={s.path} aria-current={active ? "page" : undefined} title={`⌥${i + 1}`}
                className={cn(
                  "rounded-full px-2.5 py-1.5 text-sm leading-[1.55] whitespace-nowrap transition-colors lg:px-3",
                  active ? "bg-chip font-medium text-ink" : "text-ink-2 hover:text-ink",
                )}>
                {s.label}
              </Link>
            )
          })}
        </nav>
      </div>

      <div className="flex min-w-0 items-center justify-end gap-0.5 md:gap-1.5">
        <Button variant="secondary" onClick={openOmnibar} data-search-input
          className="hidden h-[34px] w-[210px] justify-start gap-2 px-3 text-[13px] font-normal text-ink-3 hover:text-ink-2 xl:flex">
          <Search className="size-3.5" aria-hidden />종목·문서·주제 검색<Kbd className="ml-auto bg-transparent font-mono text-[11px] text-ink-3">⌘K</Kbd>
        </Button>
        <ShellButton icon={Search} label="검색 (⌘K)" onClick={openOmnibar} className="xl:hidden" />
        <HealthDot />
        <ApprovalsInbox />
        <SavedInbox />
        <SettingsMenu />
        <Button variant={aiOpen ? "default" : "secondary"} size="sm" aria-pressed={aiOpen} aria-label="AI 대화 (⌘J)" title="AI 대화 (⌘J)" onClick={onToggleAi}
          className="ml-0.5 gap-1.5 px-3 max-md:size-10 max-md:bg-transparent max-md:px-0 max-md:text-ink-2 max-md:aria-pressed:bg-chip max-md:aria-pressed:text-ink">
          <Sparkles className="size-3.5 max-md:size-[18px]" aria-hidden /><span className="max-md:sr-only">AI</span>
        </Button>
      </div>
    </header>
  )
}

/**
 * 운영 상태 — 결과 데이터 신선도(D-222). 전부 최신이면 초록, 지연·오류가 있으면 주황 + 개수.
 * 누르면 창을 연다(마우스 오버만으로는 모바일·키보드에서 못 봄 — 화면 구조 개편 §4.30): 지연·오류 목록 · 관리자 화면 링크.
 */
function HealthDot() {
  const { data, isError } = useQuery(
    apiQuery<HealthItem[]>({ key: ["spine", "admin", "health"], url: "/api/spine/admin/health", staleTime: STALE.short }),
  )
  const bad = (data ?? []).filter(h => h.status !== "ok")
  const summary = isError ? "운영 상태를 불러오지 못했습니다" : !data ? "운영 상태 확인 중"
    : !data.length ? "아직 점검할 원천이 없습니다"
    : bad.length ? `원천 ${data.length}개 중 지연·오류 ${bad.length}건` : `원천 ${data.length}개 모두 최신`
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`운영 상태 — ${summary}`}
          className="hidden h-7 gap-1.5 rounded-full px-2.5 text-xs font-normal text-muted-foreground hover:text-foreground lg:flex">
          <span aria-hidden className={cn("size-[7px] rounded-full", isError || bad.length ? "bg-chart-warning" : data ? "bg-chart-green" : "bg-muted-foreground/40")} />
          {data ? (bad.length ? `운영 ${data.length - bad.length}/${data.length}` : "운영") : "운영"}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 gap-2 p-3">
        <p className="text-sm font-medium">{summary}</p>
        {!data && !isError && <div className="space-y-1.5">{[0, 1, 2].map(i => <Skeleton key={i} className="h-4 w-full" />)}</div>}
        {bad.length > 0 && (
          <ul className="max-h-64 space-y-1.5 overflow-y-auto">
            {bad.map(h => (
              <li key={h.key} className="text-xs">
                <span className="font-medium">{h.label}</span>
                {h.critical && <span className="ml-1 text-chart-warning">핵심</span>}
                <span className="ml-1 text-muted-foreground">{STATUS_LABEL[h.status] ?? h.status}</span>
                {h.detail && <p className="text-muted-foreground">{h.detail}</p>}
              </li>
            ))}
          </ul>
        )}
        <Link to="/admin" className="flex items-center gap-0.5 text-xs text-primary hover:underline">
          관리자 화면<ChevronRight className="size-3" aria-hidden />
        </Link>
      </PopoverContent>
    </Popover>
  )
}

/** 설정 — 드물게 쓰는 것: 테마(시스템·라이트·다크) · 소스 관리 · 관리자 · 보관함 (시안 Shell-Topbar ②) */
const THEMES = [
  { value: "system", label: "시스템", icon: Monitor },
  { value: "light", label: "라이트", icon: Sun },
  { value: "dark", label: "다크", icon: Moon },
] as const
function SettingsMenu() {
  const { theme, setTheme } = useTheme()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <ShellButton icon={Settings} label="설정" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[280px]">
        <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme} aria-label="화면 테마"
          className="mx-1.5 my-1 grid grid-cols-3 gap-0.5 rounded-[10px] bg-chip p-[3px]">
          {THEMES.map(t => (
            <DropdownMenuRadioItem key={t.value} value={t.value} onSelect={e => e.preventDefault()}
              className="h-[30px] justify-center gap-1.5 rounded-lg px-2 py-0 text-[13px] font-normal text-ink-2 focus:bg-transparent focus:text-ink data-[state=checked]:bg-surface data-[state=checked]:font-medium data-[state=checked]:text-ink data-[state=checked]:shadow-[0_0_0_1px_var(--line)] [&>span:first-child]:hidden">
              <t.icon className="size-3.5" aria-hidden />{t.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild><Link to="/admin"><SlidersHorizontal /> 관리자</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/admin/sources"><Rss /> 소스 관리</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/archive"><Archive /> 보관함</Link></DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
