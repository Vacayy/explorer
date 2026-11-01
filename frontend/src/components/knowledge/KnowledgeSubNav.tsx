import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

/**
 * 월드모델 › 그래프 안의 보기 전환 (docs/specs/world-model.md §3) — 온톨로지(전체 인과 지도) ↔
 * 변화·검증 지식(최근 그래프 변화 · 흔들리는 전제 · 승격된 지식). 그래프 탭의 기본은 온톨로지.
 */
const TABS = [
  { to: "/knowledge/ontology", label: "온톨로지", active: (p: string) => p.startsWith("/knowledge/ontology") },
  { to: "/knowledge", label: "변화·검증 지식", active: (p: string) => p === "/knowledge" },
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
