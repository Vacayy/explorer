import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

/**
 * 지식 탭 내부 토글 — 지식(검증 핵심) ↔ 온톨로지(전체 인과 그래프). D-052.
 * 세계관 그래프를 지식 탭으로 통합(세계관 ⊃ 지식): 한 탭에서 전체 지도와 검증 핵심을 오간다.
 */
const TABS = [
  { to: "/knowledge", label: "지식", active: (p: string) => p === "/knowledge" },
  { to: "/knowledge/ontology", label: "온톨로지", active: (p: string) => p.startsWith("/knowledge/ontology") },
] as const

export function KnowledgeSubNav() {
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
