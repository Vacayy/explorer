import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import type { SubTab } from "./navConfig"

interface Props {
  tabs: readonly SubTab[]
  activeKey: string | null
  /** 좌측 컨텍스트 라벨 — 종목 도시에의 회사명 */
  context?: string | null
  /** 탭 뒤 동작(선택) */
  trailing?: ReactNode
}

/**
 * 인페이지 서브탭 — 모드 안의 형제 탭 전환 (docs/specs/dock-navigation.md §2).
 * 콘텍스트 첫 줄 한 행(h-8 + mb-5 = --subnav-height). URL이 상태의 단일 소스 — Link만.
 * 모드 간 점프는 도크 팝오버가, 모드 안 전환은 이 스트립이 맡는다.
 * 폰(<768): 줄 높이 h-10 + mb-3(합계는 같다) — 누르는 칸을 40px로, 알약 모양은 안쪽 span이 그린다(ia-redesign §4.32).
 */
export function SubNav({ tabs, activeKey, context, trailing }: Props) {
  return (
    <nav aria-label="하위 메뉴" className="-mx-1 mb-5 flex h-8 items-center gap-0.5 overflow-x-auto px-1 max-md:mb-3 max-md:h-10">
      {context && <span className="mr-2 shrink-0 text-sm font-semibold">{context}</span>}
      {tabs.map((t) => {
        const active = t.key === activeKey
        return (
          <Link key={t.key} to={t.path} aria-current={active ? "page" : undefined}
            className="group flex shrink-0 items-center max-md:h-10">
            <span className={cn(
              "rounded-lg px-3 py-1.5 text-[13px] leading-none transition-colors",
              active ? "bg-primary/10 font-medium text-primary" : "text-muted-foreground group-hover:bg-muted group-hover:text-foreground",
            )}>{t.label}</span>
          </Link>
        )
      })}
      {trailing}
    </nav>
  )
}
