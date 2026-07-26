import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

/**
 * 내러티브 상위 탭 내부 토글 — 내러티브(주제 서사, 빠른 층) ↔ 질문(핵심질문 분할정복 추적). D-071.
 * 지식 탭의 지식↔온톨로지 토글과 동형: 한 상위 탭에서 "지금 무슨 이야기인가"와 "무엇을 확인해야 하나"를 오간다.
 */
const TABS = [
  { to: "/narrative", label: "내러티브", active: (p: string) => p.startsWith("/narrative") },
  { to: "/questions", label: "질문", active: (p: string) => p.startsWith("/question") },
] as const

export function NarrativeSubNav() {
  const { pathname } = useLocation()
  return (
    <div className="flex gap-1">
      {TABS.map((t) => (
        <Link key={t.to} to={t.to}
          className={cn(
            "px-3 py-1 text-sm rounded-md transition-colors",
            t.active(pathname)
              ? "bg-primary text-primary-foreground font-semibold"
              : "text-muted-foreground hover:text-foreground hover:bg-muted")}>
          {t.label}
        </Link>
      ))}
    </div>
  )
}
