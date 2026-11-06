import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight } from "lucide-react"
import api from "@/api/client"
import { STALE } from "@/api/query"
import { Button } from "@/components/ui/button"
import { Card, CardHeader } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { NODE_LABEL } from "@/components/explore/graph/types"
import { useNarrativeTopics } from "@/hooks/useWorld"
import { formatNumber } from "@/utils/format"
import type { GraphActivityNode } from "@/types"

/**
 * 인과 그래프 업데이트 — 최근 7일 새로 생기거나 갱신된 노드와 수혜 후보(action_thesis, D-035).
 * 옛 /knowledge '변화·검증 지식'에 있던 것을 Thesis › 그래프(/knowledge/ontology) 그래프 아래로 되살렸다(D-308).
 * 노드 링크: 저장된 서사가 있는 주제면 서사로, 아니면(매크로·정책·사건 노드, 서사 없는 테마) 온톨로지 초점으로.
 * 서사 없는 주제로 보내면 상세가 생성을 자동 요청하거나 막다른 빈 화면이 된다.
 * 수혜 후보 계산이 무거워(단독 약 16초, 그래프와 함께면 30초 넘음) 접어 두고 펼칠 때만 부른다 — 그래프 화면이 기다리거나 시간 초과 배너를 띄우지 않게.
 */
export function GraphActivitySection() {
  const [open, setOpen] = useState(false)
  const q = useQuery({
    queryKey: ["spine", "causal", "activity"],
    queryFn: async ({ signal }) => (await api.get<GraphActivityNode[]>("/api/spine/causal/activity", { params: { days: 7, limit: 10 }, signal, timeout: 90_000 })).data,
    staleTime: STALE.medium, enabled: open,
  })
  const items = q.data ?? []
  const { topics } = useNarrativeTopics()
  const nodeLink = (n: GraphActivityNode) => topics.has(n.name)
    ? `/narrative?topic=${encodeURIComponent(n.name)}`
    : `/knowledge/ontology?focus=${n.id}`
  return (
    // 목록은 카드 안에서 펼치지 않고 옆 시트로(높이 상한과 넘침) — 열 때만 불러오는 것은 그대로
    <Card aria-label="인과 그래프 업데이트">
      <Sheet open={open} onOpenChange={setOpen}>
      <CardHeader className="flex flex-row flex-wrap items-center gap-1 space-y-0">
        <SheetTrigger asChild>
          <Button variant="ghost" className="-ml-2 h-10 gap-1 px-2 text-sm font-semibold">
            <ChevronRight className="size-4" aria-hidden />
            <h2>인과 그래프 업데이트</h2>
          </Button>
        </SheetTrigger>
        <InfoTip label="인과 그래프 업데이트 설명">최근 7일 새로 생기거나 연결이 늘어난 노드와 그 수혜 후보 종목입니다. 서사가 있는 주제는 서사로, 없으면 그래프에서 그 노드를 가운데 둡니다. 수혜 후보 계산이 무거워 펼칠 때 불러옵니다.</InfoTip>
      </CardHeader>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-xl">
      <SheetHeader className="border-b"><SheetTitle>인과 그래프 업데이트</SheetTitle><SheetDescription>최근 7일 새로 생기거나 연결이 늘어난 노드</SheetDescription></SheetHeader>
      <ScrollArea className="min-h-0 flex-1" viewportClassName="[&>div]:!block">
      <div className="space-y-1 p-4">
        {q.isFetching && !q.data && <Skeleton className="h-16 w-full" />}
        {q.isError && <ErrorState message="그래프 변화를 불러오지 못했습니다." onRetry={() => void q.refetch()} retrying={q.isFetching} />}
        {q.isSuccess && items.length === 0 && <p className="text-sm text-muted-foreground">최근 7일 인과 그래프 업데이트가 없습니다.</p>}
        {items.length > 0 && <ul className="divide-y">
          {items.map((n) => (
            <li key={n.id}>
              <Link to={nodeLink(n)} className="group block min-h-10 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-sm font-medium group-hover:underline">{n.name}</span>
                  <Badge variant="outline" className="text-[10px]">{NODE_LABEL[n.type] ?? n.type}</Badge>
                  {n.is_new
                    ? <span className="text-caption text-up-ink">신규</span>
                    : <span className="text-caption tabular-nums text-muted-foreground">갱신 +{formatNumber(n.new_edges)}</span>}
                </div>
                {n.beneficiaries.length > 0 && (
                  <div className="mt-0.5 truncate text-caption text-muted-foreground">
                    수혜 후보: {n.beneficiaries.map((b) => `${b.name}${b.rs_short != null ? ` (RS ${b.rs_short})` : ""}`).join(" · ")}
                  </div>
                )}
              </Link>
            </li>
          ))}
        </ul>}
      </div>
      </ScrollArea>
      </SheetContent>
      </Sheet>
    </Card>
  )
}
