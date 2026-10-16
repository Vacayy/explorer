import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { NODE_LABEL } from "@/components/explore/graph/types"

/**
 * 인과 그래프 업데이트 — 최근 7일 새로 생기거나 갱신된 노드와 수혜 후보.
 * Home 시장 탭에서 월드모델 내러티브 랜딩으로 옮김 (D-208: 시장=상태, 피드=읽을거리, 그래프 변화=월드모델).
 */

/* ---------- 인과 그래프 활동 — 새로 뜬/갱신된 노드 + 수혜 종목 (action_thesis, D-035) ---------- */

interface ActivityBeneficiary { stock_code: string; name: string; rs_short: number | null }
interface GraphActivityNode {
  id: number; name: string; type: string; is_new: boolean; new_edges: number
  beneficiaries: ActivityBeneficiary[]
}

export function GraphActivitySection() {
  const { data } = useQuery(
    apiQuery<GraphActivityNode[]>({
      key: ["spine", "causal", "activity"],
      url: "/api/spine/causal/activity?days=7&limit=10",
      staleTime: STALE.medium,
    }),
  )
  const items = data ?? []
  return (
    <Card>
      <CardHeader className="pb-2 flex flex-wrap items-center gap-2">
        <CardTitle className="text-sm">인과 그래프 업데이트</CardTitle>
        <span className="text-[11px] text-muted-foreground">새로 추가·갱신된 노드와 수혜 종목</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 && <p className="text-sm text-muted-foreground">최근 인과 그래프 업데이트가 없습니다.</p>}
        {items.map((n) => (
          <Link key={n.id} to={`/narrative?topic=${encodeURIComponent(n.name)}`} className="block group">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-medium text-sm group-hover:underline">{n.name}</span>
              <Badge variant="outline" className="text-[9px]">{NODE_LABEL[n.type] ?? n.type}</Badge>
              {n.is_new
                ? <span className="text-[10px] text-up">신규</span>
                : <span className="text-[10px] text-muted-foreground tabular-nums">갱신 +{n.new_edges}</span>}
            </div>
            {n.beneficiaries.length > 0 && (
              <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
                수혜 후보: {n.beneficiaries.map((b) => `${b.name}${b.rs_short != null ? ` (RS ${b.rs_short})` : ""}`).join(" · ")}
              </div>
            )}
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}
