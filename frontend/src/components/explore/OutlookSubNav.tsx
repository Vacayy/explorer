import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

/**
 * 전망(미래·확률) 상위 탭 내부 토글 — 질문(핵심질문 추적) ↔ 리포트(투자 판단·콜). D-073.
 * 인식론적 시간축: 지식=과거·검증 / 내러티브=현재·서사 / 전망=미래·확률.
 * 미래-확률이 질문·리포트로 흩어져 있던 것을 한 상위 탭으로 집약 (지식↔온톨로지와 동형).
 */
const TABS = [
  { to: "/thesis", label: "논지 감사", active: (p: string) => p.startsWith("/thesis") },
  { to: "/questions", label: "질문", active: (p: string) => p.startsWith("/question") },
  { to: "/report", label: "리포트", active: (p: string) => p.startsWith("/report") },
] as const

export function OutlookSubNav() {
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
