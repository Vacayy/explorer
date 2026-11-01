import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { NODE_LABEL } from "@/components/explore/graph/types"
import { useNarrativeTopics } from "@/hooks/useWorld"

/**
 * 인과 그래프 업데이트 — 최근 7일 새로 생기거나 갱신된 노드와 수혜 후보.
 * 월드모델 › 그래프 › 변화·검증 지식에 둔다 (docs/specs/world-model.md §3).
 * 노드 링크: 저장된 서사가 있는 주제면 서사로, 아니면(매크로·정책·사건 노드, 서사 없는 테마) 온톨로지 초점으로.
 * 서사 없는 주제로 보내면 상세가 생성을 자동 요청하거나 막다른 빈 화면이 된다.
 */

/* ---------- 인과 그래프 활동 — 새로 뜬/갱신된 노드 + 수혜 종목 (action_thesis, D-035) ---------- */

interface ActivityBeneficiary { stock_code: string; name: string; rs_short: number | null }
interface GraphActivityNode {
  id: number; name: string; type: string; is_new: boolean; new_edges: number
  beneficiaries: ActivityBeneficiary[]
}

export function GraphActivitySection() {
  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<GraphActivityNode[]>({
      key: ["spine", "causal", "activity"],
      url: "/api/spine/causal/activity?days=7&limit=10",
      staleTime: STALE.medium,
    }),
  )
  const items = data ?? []
  const { topics } = useNarrativeTopics()
  const nodeLink = (n: GraphActivityNode) => topics.has(n.name)
    ? `/narrative?topic=${encodeURIComponent(n.name)}`
    : `/knowledge/ontology?focus=${n.id}`
  return (
    <Card>
      <CardHeader className="pb-2 flex flex-wrap items-center gap-2">
        <CardTitle className="text-sm">인과 그래프 업데이트</CardTitle>
        <span className="text-[11px] text-muted-foreground">새로 추가·갱신된 노드와 수혜 종목</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && <Skeleton className="h-16 w-full" />}
        {isError && <ErrorState message="그래프 변화를 불러오지 못했습니다." onRetry={() => void refetch()} />}
        {!isLoading && !isError && items.length === 0 && <p className="text-sm text-muted-foreground">최근 7일 인과 그래프 업데이트가 없습니다.</p>}
        {items.map((n) => (
          <Link key={n.id} to={nodeLink(n)} className="block group">
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
