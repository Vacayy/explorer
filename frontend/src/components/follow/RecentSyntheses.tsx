// 최근 교차 종합 — 일회성 산출물(D-104)의 재열람 경로. 없으면 아무것도 안 그린다.
import { Link } from "react-router-dom"
import { Layers } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { formatRelativeTime } from "@/utils/format"
import { useSyntheses } from "@/hooks/useSynthesis"

function when(created_at: string | null): string {
  if (!created_at) return "-"
  return formatRelativeTime(created_at.includes("T") ? created_at : created_at.replace(" ", "T") + "Z")
}

export default function RecentSyntheses() {
  const { data: items = [] } = useSyntheses(5)
  if (items.length === 0) return null

  return (
    <Card>
      <CardContent className="space-y-1 py-3">
        <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
          <Layers className="h-3.5 w-3.5 text-muted-foreground" /> 최근 교차 종합
        </h2>
        <ul className="divide-y">
          {items.map((s) => (
            <li key={s.id} className="flex items-center gap-2 py-2">
              <Link
                to={`/synthesis/${s.id}`}
                className="min-w-0 flex-1 truncate text-sm hover:text-primary hover:underline"
              >
                {s.title || `문서 ${s.doc_count}건 교차 종합`}
              </Link>
              <span className="shrink-0 text-xs text-muted-foreground">문서 {s.doc_count}건</span>
              <span className="shrink-0 text-xs text-muted-foreground">{when(s.created_at)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
