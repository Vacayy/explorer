import { NavLink, useLocation } from "react-router-dom"
import { Compass, Globe, House, Layers, PieChart, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { SECTIONS, locate, type SectionKey } from "./navConfig"

const ICONS: Record<SectionKey, LucideIcon> = { home: House, explore: Compass, portfolio: PieChart, canvas: Layers, world: Globe }

/**
 * 모바일 하단 탭바 — 폭 <768에서 상단 L1 5탭을 대신한다 (docs/specs/app-shell.md §6).
 * 활성 판정은 상단 바와 같은 navConfig.locate. 하위 탭은 본문 첫 줄 SubNav가 맡는다.
 */
export function TabBar() {
  const { pathname, search } = useLocation()
  const here = locate(pathname, search)
  return (
    <nav aria-label="메인"
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t bg-background pb-[env(safe-area-inset-bottom)] md:hidden">
      {SECTIONS.map(s => {
        const Icon = ICONS[s.key]
        const active = here?.section === s.key
        return (
          <NavLink key={s.key} to={s.path} aria-current={active ? "page" : undefined}
            className={cn("flex h-(--tabbar-height) flex-col items-center justify-center gap-0.5 text-[11px] transition-colors",
              active ? "font-semibold text-primary" : "text-muted-foreground")}>
            <Icon className="size-5" aria-hidden />
            {s.label}
          </NavLink>
        )
      })}
    </nav>
  )
}
