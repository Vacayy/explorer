import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import type { SubTab } from "./navConfig"

interface Props {
  tabs: readonly SubTab[]
  activeKey: string | null
  /** 좌측 컨텍스트 라벨 — 종목 도시에의 회사명 */
  context?: string | null
}

/**
 * 인페이지 서브탭 — 모드 안의 형제 탭 전환 (docs/specs/dock-navigation.md §2).
 * 콘텍스트 첫 줄 한 행(h-8 + mb-5 = --subnav-height). URL이 상태의 단일 소스 — Link만.
 * 모드 간 점프는 도크 팝오버가, 모드 안 전환은 이 스트립이 맡는다.
 */
export function SubNav({ tabs, activeKey, context }: Props) {
  return (
    <nav aria-label="하위 메뉴" className="-mx-1 mb-5 flex h-8 items-center gap-0.5 overflow-x-auto px-1">
      {context && <span className="mr-2 shrink-0 text-sm font-semibold">{context}</span>}
      {tabs.map((t) => {
        const active = t.key === activeKey
        return (
          <Link key={t.key} to={t.path} aria-current={active ? "page" : undefined}
            className={cn(
              "shrink-0 rounded-lg px-3 py-1.5 text-[13px] leading-none transition-colors",
              active ? "bg-primary/10 font-medium text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}>
            {t.label}
          </Link>
        )
      })}
    </nav>
  )
}
