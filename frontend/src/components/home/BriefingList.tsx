import { Link } from "react-router-dom"
import { AlertTriangle, BadgeCheck, Building2, Lightbulb, LineChart, Swords } from "lucide-react"
import type { BriefItem } from "@/types"

/** 기계의 3줄(소스 경고·가설 확인/충돌·공시 등) — 홈 상단이 아니라 인박스 '공지'로 이관 (D-054). */
const BRIEF_ICON = {
  insight: Lightbulb, action: Building2, signal: LineChart,
  warning: AlertTriangle, conflict: Swords, confirmed: BadgeCheck,
} as const

export function BriefingList({ items }: { items: BriefItem[] }) {
  if (!items.length) return null
  return (
    <ul className="space-y-1.5">
      {items.map((b, i) => {
        const Icon = BRIEF_ICON[b.kind as keyof typeof BRIEF_ICON] ?? Lightbulb
        return (
          <li key={i}>
            <Link to={b.to} className="group flex items-start gap-2 text-sm">
              <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${b.kind === "insight" ? "text-hypothesis" : b.kind === "warning" || b.kind === "conflict" ? "text-destructive" : "text-muted-foreground"}`} />
              <span className="group-hover:underline leading-snug">{b.text}</span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
