import { Swords } from "lucide-react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { useContestedPremises } from "@/hooks/useWorld"
import { formatDbRelative } from "@/utils/format"
import type { WorldContestedItem } from "@/types"

export const PACE_LABEL: Record<string, string> = {
  event: "사건", flow: "흐름", cycle: "사이클", structure: "구조", regime: "체제",
}

/** 흔들리는 전제 한 줄 — 진술 · 층 · 반박/지지 수 · 최근 반례 문서. 그래프 화면과 위젯이 같이 쓴다 */
export function ContestedRow({ k, clamp = 2 }: { k: WorldContestedItem; clamp?: number }) {
  const doc = k.latest_refute
  return <li className="space-y-1">
    <p className={clamp === 1 ? "line-clamp-1 text-sm" : "line-clamp-2 text-sm"}>{k.statement}</p>
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
      <Badge variant="secondary" className="text-[10px]">{PACE_LABEL[k.pace_layer] ?? k.pace_layer}</Badge>
      <span className="tabular-nums">반박 {k.refute} · 지지 {k.support}</span>
      {doc?.doc_id != null && <Link to={`/doc/${doc.doc_id}`} className="min-w-0 truncate hover:text-foreground hover:underline">반례: {doc.title ?? `문서 ${doc.doc_id}`}</Link>}
      <span className="ml-auto shrink-0 tabular-nums">충돌 {formatDbRelative(k.contested_at)}</span>
    </div>
  </li>
}

/** 흔들리는 전제 — 검증 지식 중 반례가 쌓여 충돌 중인 것 */
export function ContestedPremisesCard() {
  const q = useContestedPremises()
  return <Card className="border-l-2 border-l-hypothesis">
    <CardHeader className="flex flex-row flex-wrap items-baseline gap-2 pb-2">
      <CardTitle className="flex items-center gap-1.5 text-sm"><Swords aria-hidden="true" className="size-4 text-hypothesis" />흔들리는 전제</CardTitle>
      <span className="text-[11px] text-muted-foreground">검증된 지식 중 반례가 들어와 충돌 중인 것</span>
      {q.data && <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{q.data.items.length}건</span>}
    </CardHeader>
    <CardContent>
      {q.isLoading ? <Skeleton className="h-16 w-full" />
        : q.isError ? <ErrorState message="흔들리는 전제를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : !q.data?.items.length ? <EmptyState message="지금 충돌 중인 전제는 없습니다." />
        : <ul className="space-y-3">{q.data.items.map(k => <ContestedRow key={k.id} k={k} />)}</ul>}
    </CardContent>
  </Card>
}
