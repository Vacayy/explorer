import { Link } from "react-router-dom"
import { ChevronRight } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Spark } from "@/components/shared/Spark"
import { cn } from "@/lib/utils"

/**
 * Signal Summary Card — 한 신호 유형의 순위 목록을 약식 스파크와 함께 한눈에.
 * 헤더/영역 클릭 → 해당 유형 상세(목록) 뷰로. 개별 항목은 자기 링크로.
 */
export interface SummaryRow {
  key: string
  rank: number
  name: string
  link?: string          // 이름 클릭 목적지 (없으면 일반 텍스트)
  spark?: number[]
  metric: string         // 주 지표 (예: "7일 20회")
  sub?: string           // 부가 (예: "직전 0")
  badge?: string         // 강조 (예: "×20", "신규")
}

export function SignalSummaryCard({ title, subtitle, rows, onOpen }: {
  title: string
  subtitle?: string
  rows: SummaryRow[]
  onOpen?: () => void
}) {
  return (
    <Card className={cn(onOpen && "cursor-pointer hover:border-primary/40 transition-colors")}>
      <CardHeader className="pb-2 flex-row flex-wrap items-center gap-2" onClick={onOpen}>
        <CardTitle className="text-sm">{title}</CardTitle>
        {subtitle && <span className="text-[11px] text-muted-foreground">{subtitle}</span>}
        {onOpen && (
          <span className="ml-auto flex items-center gap-0.5 text-[11px] text-muted-foreground">
            전체 보기 <ChevronRight className="h-3.5 w-3.5" />
          </span>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-y-1">
          {rows.length === 0 && <p className="text-sm text-muted-foreground">표시할 순위가 없습니다.</p>}
          {rows.map((r) => (
            <div key={r.key} className="flex items-center gap-2 py-1 text-sm min-w-0">
              <span className="w-5 text-right text-xs text-muted-foreground tabular-nums shrink-0">{r.rank}</span>
              {r.link ? (
                <Link to={r.link} onClick={(e) => e.stopPropagation()}
                  className="font-medium text-primary hover:underline truncate">{r.name}</Link>
              ) : <span className="font-medium truncate">{r.name}</span>}
              <span className="ml-auto shrink-0 flex items-center gap-1.5 text-xs tabular-nums">
                {r.spark && r.spark.length > 0 && <Spark data={r.spark} />}
                <span className="font-medium">{r.metric}</span>
                {r.sub && <span className="text-muted-foreground">({r.sub})</span>}
                {r.badge && <span className="text-up">{r.badge}</span>}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
