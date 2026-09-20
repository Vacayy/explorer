import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { useTheme } from "next-themes"
import { Archive, Building2, BookOpen, Ellipsis, FileSearch, Rss, FlaskConical, Moon, PanelRight, Search, SlidersHorizontal, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useSidebar } from "@/components/ui/sidebar"
import { useIsMobile } from "@/hooks/use-mobile"
import { cn } from "@/lib/utils"
import { DockItem } from "./DockItem"
import { ApprovalsInbox, SavedInbox } from "./Inboxes"
import { MODES, analyzeTabs, companyResearchSearch, dockModeOf, getActiveMode, getActiveSubTab, type ModeDef, type SubTab } from "@/components/layout/navConfig"

interface Props {
  stockCode: string | null
  companyName?: string | null
}

/** 옴니바(⌘K) 열기 — Omnibar가 document keydown을 듣는다 */
export function openOmnibar() {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
}

/**
 * 도크 — 헤더·ModeNavigation을 대체하는 하단 플로팅 내비 (docs/specs/dock-navigation.md, D-136).
 *   [검색] │ Home ┃ 팔로우 · 피드 · 월드모델 ┃ 대화 │ [열린 도시에] │ 승인 · 저장 · 레일 · 더보기
 * L1 순서·구분선은 D-057 그대로. L2는 호버 팝오버(모드 간 점프) — 모드 안 전환은 인페이지 SubNav.
 * 열린 도시에 = macOS "실행 중 앱" 관용구: /analyze·/us에 있을 때만 나타나는 임시 항목.
 * <768: 전폭 하단 탭바(5모드 + 더보기), 활성 탭 재탭 → L2 Sheet.
 */
export default function Dock({ stockCode, companyName }: Props) {
  const { pathname, search } = useLocation()
  const mode = getActiveMode(pathname)
  const activeL1 = dockModeOf(mode)
  const activeSub = getActiveSubTab(pathname, search)
  const isMobile = useIsMobile()

  // 열린 도시에 — KR 종목(/analyze/:code) 또는 미국 티커(/us/:ticker)
  const usTicker = pathname.match(/^\/us\/([^/]+)/)?.[1] ?? null
  const dossier = stockCode
    ? { label: companyName ?? stockCode, to: `/analyze/${stockCode}/summary${companyResearchSearch(search)}`, tabs: analyzeTabs(stockCode, search) }
    : usTicker ? { label: usTicker, to: `/us/${usTicker}`, tabs: [] as SubTab[] } : null

  if (isMobile) return <MobileTabBar activeL1={activeL1} activeSub={activeSub} />

  return (
    <nav aria-label="주 메뉴"
      className="fixed bottom-4 left-1/2 z-40 flex h-14 -translate-x-1/2 items-center gap-0.5 rounded-2xl glass-surface p-1">
      <DockItem icon={Search} label="검색" onClick={openOmnibar} aria-label="검색 · 이동 · 질문 (⌘K)" data-search-input />
      <Divider />

      {MODES.map((m) => (
        <span key={m.key} className="contents">
          {m.dividerBefore && <Divider />}
          <ModeItem m={m} active={activeL1 === m.key} activeSub={activeSub} />
        </span>
      ))}

      {dossier && (
        <>
          <Divider />
          <WithTabs title={dossier.label} tabs={dossier.tabs} activeSub={activeSub}>
            <DockItem icon={Building2} label={dossier.label} to={dossier.to} active
              className="w-auto min-w-14 max-w-32 px-2 [&>span:first-of-type]:max-w-full [&>span:first-of-type]:truncate" />
          </WithTabs>
        </>
      )}

      <Divider />
      <ApprovalsInbox />
      <SavedInbox />
      <RailToggle />
      <MoreMenu />
    </nav>
  )
}

function Divider() {
  return <span aria-hidden className="mx-0.5 h-6 w-px shrink-0 bg-border" />
}

function ModeItem({ m, active, activeSub }: { m: ModeDef; active: boolean; activeSub: string | null }) {
  const item = <DockItem icon={m.icon} label={m.label} to={m.path} active={active} emphasis={m.emphasis} />
  if (!m.tabs) return item
  return <WithTabs title={m.label} tabs={m.tabs} activeSub={activeSub}>{item}</WithTabs>
}

/** 호버 250ms → 위로 여는 L2 팝오버. 단순 클릭은 모드 랜딩(빠른 길). 탭이 없으면 그대로 */
function WithTabs({ title, tabs, activeSub, children }: { title: string; tabs: readonly SubTab[]; activeSub: string | null; children: React.ReactNode }) {
  if (tabs.length === 0) return <>{children}</>
  return (
    <HoverCard openDelay={250} closeDelay={120}>
      <HoverCardTrigger asChild>{children}</HoverCardTrigger>
      <HoverCardContent side="top" sideOffset={10} className="w-auto max-w-sm rounded-2xl p-2">
        <p className="px-2 pb-1.5 pt-1 text-[11px] font-medium text-muted-foreground">{title}</p>
        <div className="grid grid-cols-3 gap-0.5">
          {tabs.map((t) => (
            <Button key={t.key} variant="ghost" size="sm" asChild
              className={cn("h-8 justify-start rounded-lg px-2.5 text-[13px] font-normal", t.key === activeSub && "bg-primary/10 font-medium text-primary hover:bg-primary/15 hover:text-primary")}>
              <Link to={t.path}>{t.label}</Link>
            </Button>
          ))}
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

function RailToggle({ compact }: { compact?: boolean }) {
  const { toggleSidebar } = useSidebar()
  return <DockItem icon={PanelRight} label="레일" onClick={toggleSidebar} aria-label="팔로우 레일 토글 (⌘B)" className={compact ? "w-full" : undefined} />
}

/** 더보기 — 드물게 쓰는 것: 테마 · 관리자 · 보관함 */
function MoreMenu() {
  const { resolvedTheme, setTheme } = useTheme()
  const dark = resolvedTheme === "dark"
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <DockItem icon={Ellipsis} label="더보기" />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" sideOffset={10} className="min-w-44">
        <DropdownMenuItem onSelect={() => setTheme(dark ? "light" : "dark")}>
          {dark ? <Sun /> : <Moon />} {dark ? "라이트 모드" : "다크 모드"}
        </DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/feed?view=documents"><FileSearch /> 문서 검색</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/sources"><Rss /> 소스 관리</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/admin"><SlidersHorizontal /> 관리자</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/experiments/expectations"><FlaskConical /> 메모리 리서치</Link></DropdownMenuItem>
        <DropdownMenuItem asChild><Link to="/archive"><Archive /> 보관함</Link></DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* ───────────── 모바일 (<768): 전폭 하단 탭바 ───────────── */

function MobileTabBar({ activeL1, activeSub }: { activeL1: string; activeSub: string | null }) {
  const [l2, setL2] = useState<ModeDef | null>(null)      // 활성 탭 재탭 → L2 Sheet
  const [more, setMore] = useState(false)
  const { resolvedTheme, setTheme } = useTheme()
  const dark = resolvedTheme === "dark"

  return (
    <>
      {/* 열린 도시에 탭은 인페이지 SubNav가 이미 보여준다(모바일은 상단 스트립만) */}
      <nav aria-label="주 메뉴"
        className="fixed inset-x-0 bottom-0 z-40 grid h-[var(--dock-height)] grid-cols-6 items-center glass-surface px-1 pb-[env(safe-area-inset-bottom)]">
        {MODES.filter(m => m.key !== 'study').map((m) => {
          const active = activeL1 === m.key
          // 활성 + 하위 탭 있음 → 이동 대신 L2 Sheet (iOS "탭 재탭" 관용구)
          return active && m.tabs
            ? <DockItem key={m.key} icon={m.icon} label={m.label} active className="w-full" onClick={() => setL2(m)} />
            : <DockItem key={m.key} icon={m.icon} label={m.label} to={m.path} active={active} className="w-full" />
        })}
        <DockItem icon={Ellipsis} label="더보기" active={activeL1 === 'study'} className="w-full" onClick={() => setMore(true)} />
      </nav>

      <Sheet open={!!l2} onOpenChange={(o) => !o && setL2(null)}>
        <SheetContent side="bottom" className="rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]">
          <SheetHeader><SheetTitle>{l2?.label}</SheetTitle></SheetHeader>
          <div className="grid grid-cols-3 gap-1 px-4 pb-2">
            {l2?.tabs?.map((t) => (
              <Button key={t.key} variant="ghost" size="sm" asChild onClick={() => setL2(null)}
                className={cn("h-9 justify-start rounded-lg", t.key === activeSub && "bg-primary/10 font-medium text-primary")}>
                <Link to={t.path}>{t.label}</Link>
              </Button>
            ))}
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={more} onOpenChange={setMore}>
        <SheetContent side="bottom" className="rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]">
          <SheetHeader><SheetTitle>더보기</SheetTitle></SheetHeader>
          <div className="grid grid-cols-4 gap-1 px-4 pb-2" onClick={(e) => { if ((e.target as HTMLElement).closest("a,button")) setMore(false) }}>
            <DockItem icon={Search} label="검색" className="w-full" onClick={openOmnibar} />
            <DockItem icon={BookOpen} label="스터디" to="/study" active={activeL1 === 'study'} className="w-full" />
            <DockItem icon={FileSearch} label="문서 검색" to="/feed?view=documents" className="w-full" />
            <DockItem icon={Rss} label="소스 관리" to="/sources" className="w-full" />
            <ApprovalsInbox compact />
            <SavedInbox compact />
            <RailToggle compact />
            <DockItem icon={dark ? Sun : Moon} label={dark ? "라이트" : "다크"} className="w-full" onClick={() => setTheme(dark ? "light" : "dark")} />
            <DockItem icon={SlidersHorizontal} label="관리자" to="/admin" className="w-full" />
            <DockItem icon={FlaskConical} label="메모리 리서치" to="/experiments/expectations" className="w-full" />
            <DockItem icon={Archive} label="보관함" to="/archive" className="w-full" />
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
