import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

/**
 * 월드모델 › 내 판단 안의 보기 전환 (docs/specs/world-model.md §4) — 질문(기본) · 논지 감사 · 리포트 · 프록시 보드(D-240).
 * 질문이 1급 객체다: 보유 논지·관심 이유·논지 감사 승격·서사 도출이 모두 같은 질문 행으로 쌓인다.
 */
const TABS = [
  { to: "/questions", label: "질문", active: (p: string) => p.startsWith("/question") },
  { to: "/thesis", label: "논지 감사", active: (p: string) => p.startsWith("/thesis") },
  { to: "/report", label: "리포트", active: (p: string) => p.startsWith("/report") },
  { to: "/proxy-boards", label: "프록시 보드", active: (p: string) => p.startsWith("/proxy-boards") },
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
