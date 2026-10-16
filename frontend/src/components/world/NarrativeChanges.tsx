import { ArrowRight, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { useNarrativeChanges } from "@/hooks/useWorld"
import { cn } from "@/lib/utils"
import { formatDbRelative } from "@/utils/format"
import type { WorldEdgeBrief, WorldNarrativeChange } from "@/types"

/** 고리 하나 — '+ A → B'(새로 생김) / '− A → B'(사라짐). 화살표 색 = 효과 방향 */
function EdgeChip({ e, kind }: { e: WorldEdgeBrief; kind: "added" | "removed" }) {
  return <span className={cn("inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px]",
    kind === "removed" && "text-muted-foreground line-through decoration-muted-foreground/50")}>
    <span aria-hidden="true" className={kind === "added" ? "text-primary" : "text-muted-foreground"}>{kind === "added" ? "+" : "−"}</span>
    <span className="truncate">{e.from}</span>
    <ArrowRight aria-hidden="true" className={cn("size-3 shrink-0", e.effect_direction === "positive" ? "text-up" : e.effect_direction === "negative" ? "text-down" : "text-muted-foreground")} />
    <span className="truncate">{e.to}</span>
  </span>
}

/** 바뀐 서사 한 줄 — 제목 · 바뀐 것 한 줄 · 추가/삭제 고리. 랜딩과 위젯이 같이 쓴다 */
export function NarrativeChangeRow({ item, edges = 3 }: { item: WorldNarrativeChange; edges?: number }) {
  return <li className="space-y-1">
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <Link to={`/narrative?topic=${encodeURIComponent(item.topic)}`} className="text-sm font-medium leading-snug hover:underline">{item.title ?? item.topic}</Link>
      <Badge variant="outline" className="text-[10px]">{item.topic}</Badge>
      <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">v{item.version} · {formatDbRelative(item.created_at)}</span>
    </div>
    {item.is_first
      ? <p className="text-xs text-muted-foreground">새로 생긴 서사입니다.</p>
      : item.drift_summary && <p className="line-clamp-2 text-xs"><span className="text-hypothesis">바뀐 것 </span><span className="text-muted-foreground">{item.drift_summary}</span></p>}
    {edges > 0 && (item.added_count > 0 || item.removed_count > 0) && <div className="flex flex-wrap items-center gap-1">
      {item.added_edges.slice(0, edges).map((e, i) => <EdgeChip key={`a${i}`} e={e} kind="added" />)}
      {item.removed_edges.slice(0, Math.max(1, edges - 1)).map((e, i) => <EdgeChip key={`r${i}`} e={e} kind="removed" />)}
      <span className="text-[11px] text-muted-foreground tabular-nums">고리 +{item.added_count} / −{item.removed_count}</span>
    </div>}
  </li>
}

const FIRST = 5   // 처음엔 최근 5편만 — 나머지는 펼쳐서

/** 이번 주 바뀐 서사 — 최근 7일 새 버전 (저장된 drift + 결정적 diff, 생성 없음) */
export function NarrativeChangesCard() {
  const q = useNarrativeChanges(7)
  return <Card>
    <CardHeader className="flex flex-row flex-wrap items-baseline gap-2 pb-2">
      <CardTitle className="text-sm">이번 주 바뀐 서사</CardTitle>
      <span className="text-[11px] text-muted-foreground">최근 7일 새 버전 · 무엇이 바뀌었나와 새로 생기거나 사라진 인과 고리</span>
      {q.data && <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{q.data.items.length}편</span>}
    </CardHeader>
    <CardContent>
      {q.isLoading ? <div className="space-y-3"><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /></div>
        : q.isError ? <ErrorState message="바뀐 서사를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : !q.data?.items.length ? <EmptyState message="최근 7일 동안 새 버전이 나온 서사가 없습니다." />
        : <Collapsible className="space-y-3">
            <ul className="space-y-3">{q.data.items.slice(0, FIRST).map(i => <NarrativeChangeRow key={i.narrative_id} item={i} />)}</ul>
            {q.data.items.length > FIRST && <>
              <CollapsibleContent><ul className="space-y-3">{q.data.items.slice(FIRST).map(i => <NarrativeChangeRow key={i.narrative_id} item={i} />)}</ul></CollapsibleContent>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="group text-muted-foreground">
                  <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />
                  <span className="group-data-[state=open]:hidden">{q.data.items.length - FIRST}편 더 보기</span>
                  <span className="hidden group-data-[state=open]:inline">접기</span>
                </Button>
              </CollapsibleTrigger>
            </>}
          </Collapsible>}
    </CardContent>
  </Card>
}
