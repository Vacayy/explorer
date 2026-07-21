import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { PageContainer } from "@/components/shared/PageContainer"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { EdgeContextRow, BeneficiaryList } from "@/components/explore/graph/CausalDetail"
import { NODE_LABEL, type WEdge } from "@/components/explore/graph/types"

/**
 * /issue/:nodeId — 이슈 디테일. 신호 탭 '인과 그래프 활동'에서 진입.
 * "이 이슈가 어떤 논리(원인→결과)로 어떤 종목 수혜로 가고, 업사이드/하방은 어떤지"를 한 흐름으로.
 * 세계관 노드로 점프하는 대신, 논리+수혜+업사이드를 페이지에서 직접 해소.
 */
interface IssueNode {
  id: number; name: string; type: string
  in_degree: number; out_degree: number
}
interface NodeContext {
  node: IssueNode | null
  causes: WEdge[]
  effects: WEdge[]
}

export default function IssueDetailPage() {
  const { nodeId } = useParams()
  const navigate = useNavigate()
  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<NodeContext>({
      key: ["spine", "causal", "node", nodeId ?? "", "context"],
      url: `/api/spine/causal/node/${nodeId}/context`,
      staleTime: STALE.short,
      enabled: !!nodeId,
    }),
  )

  if (isLoading) {
    return <PageContainer gap="sm"><Skeleton className="h-8 w-80" /><Skeleton className="h-64 w-full rounded-xl" /></PageContainer>
  }
  if (isError || !data?.node) return <ErrorState message="이슈를 불러오지 못했습니다" onRetry={() => refetch()} />

  const { node, causes, effects } = data
  const showBeneficiaries = node.type !== "company"

  return (
    <PageContainer gap="sm" width="reading">
      <div className="flex items-center gap-2 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate("/explore")}>
          <ArrowLeft className="h-4 w-4" /> 신호
        </Button>
        <Badge variant="secondary" className="text-[10px]">{NODE_LABEL[node.type] ?? node.type}</Badge>
      </div>

      <h1 className="text-xl font-bold leading-snug">{node.name}</h1>
      <div className="text-xs text-muted-foreground">
        인과 연결 — 원인 {causes.length} · 결과 {effects.length}
      </div>

      {/* 인과 논리: 무엇이 이 이슈를 부르고(원인) → 이 이슈가 무엇으로 이어지나(결과) */}
      {causes.length === 0 && effects.length === 0 ? (
        <EmptyState message="아직 이 이슈에 연결된 인과가 없습니다 — 내러티브가 쌓이면 채워집니다." />
      ) : (
        <>
          {causes.length > 0 && (
            <div>
              <div className="text-sm font-medium mb-1.5">이 이슈를 부르는 원인</div>
              <ul className="space-y-1.5">{causes.map((e, i) => <EdgeContextRow key={`c${i}`} e={e} dir="in" />)}</ul>
            </div>
          )}
          {effects.length > 0 && (
            <div>
              <div className="text-sm font-medium mb-1.5">이 이슈가 부르는 결과 (→ 수혜)</div>
              <ul className="space-y-1.5">{effects.map((e, i) => <EdgeContextRow key={`e${i}`} e={e} dir="out" />)}</ul>
            </div>
          )}
        </>
      )}

      {/* 수혜 종목 + 업사이드/하방 (각 종목 '업사이드' 버튼) */}
      {showBeneficiaries && <BeneficiaryList sector={node.name} />}
    </PageContainer>
  )
}
