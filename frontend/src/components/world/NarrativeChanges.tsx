import { ArrowRight, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { useNarrativeChanges } from "@/hooks/useWorld"
import { cn } from "@/lib/utils"
import { kstDay } from "@/lib/bigPicture"
import type { WorldEdgeBrief, WorldNarrativeChange } from "@/types"

/** 고리 하나 — '+ A → B'(새로 생김) / '− A → B'(사라짐). 화살표 색 = 효과 방향 */
function EdgeChip({ e, kind }: { e: WorldEdgeBrief; kind: "added" | "removed" }) {
  return <span className={cn("inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px]",
    kind === "removed" && "text-muted-foreground line-through decoration-muted-foreground/50")}>
    <span aria-hidden="true" className={kind === "added" ? "text-primary" : "text-muted-foreground"}>{kind === "added" ? "+" : "−"}</span>
    <span className="truncate">{e.from}</span>
    <ArrowRight aria-hidden="true" className={cn("size-3 shrink-0", e.effect_direction === "positive" ? "text-up-ink" : e.effect_direction === "negative" ? "text-down-ink" : "text-muted-foreground")} />
    <span className="truncate">{e.to}</span>
  </span>
}

/** 바뀐 서사 한 줄(Narrative 시안) — 제목 · 주제 · v·날짜 | 고리 +n / −m, '바뀐 것' 한 줄, 추가/삭제 고리 칩(모바일은 숨김 — 상세에서 본다) */
export function NarrativeChangeRow({ item, edges = 3 }: { item: WorldNarrativeChange; edges?: number }) {
  const changed = item.change_summary ?? item.drift_summary
  return <li className="space-y-1.5 py-3" data-change-row>
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <Link to={`/narrative?topic=${encodeURIComponent(item.topic)}`} className="min-w-0 text-sm font-semibold leading-snug hover:underline">{item.title ?? item.topic}</Link>
      <Badge variant="secondary" className="text-[10px]">{item.topic}</Badge>
      <span className="font-mono text-[11px] text-muted-foreground tabular-nums">v{item.version} · {kstDay(item.created_at)}</span>
      {(item.added_count > 0 || item.removed_count > 0) && <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums">고리 +{item.added_count} / −{item.removed_count}</span>}
    </div>
    {item.is_first
      ? <p className="text-xs text-muted-foreground">새로 생긴 서사입니다.</p>
      : changed && <p className="line-clamp-2 text-xs text-muted-foreground"><span className="text-foreground">바뀐 것 · </span>{changed}</p>}
    {edges > 0 && (item.added_count > 0 || item.removed_count > 0) && <div className="hidden flex-wrap items-center gap-1 sm:flex">
      {item.added_edges.slice(0, edges).map((e, i) => <EdgeChip key={`a${i}`} e={e} kind="added" />)}
      {item.removed_edges.slice(0, Math.max(1, edges - 1)).map((e, i) => <EdgeChip key={`r${i}`} e={e} kind="removed" />)}
    </div>}
  </li>
}

const FIRST = 5   // 처음엔 최근 5편만 — 나머지는 펼쳐서

/** [내러티브] 이번주 업데이트 — 최근 7일 새 버전 (저장된 요약 + 결정적 diff, 생성 없음) */
export function NarrativeChangesCard() {
  const q = useNarrativeChanges(7)
  return <Card className="gap-0 py-0" aria-label="이번주 업데이트">
    <header className="flex flex-wrap items-baseline gap-x-2 border-b px-4 py-3">
      <h2 className="text-section font-semibold">[내러티브] 이번주 업데이트</h2>
      <span className="text-caption text-muted-foreground">최근 7일 새 버전</span>
      {q.data && <span className="ml-auto font-mono text-caption tabular-nums">{q.data.items.length}편</span>}
    </header>
    <div className="px-4 pb-2">
      {q.isLoading ? <div className="space-y-3 py-3"><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /></div>
        : q.isError ? <ErrorState message="바뀐 서사를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : !q.data?.items.length ? <EmptyState message="최근 7일 동안 새 버전이 나온 서사가 없습니다." />
        : <Collapsible>
            <ul className="divide-y">{q.data.items.slice(0, FIRST).map(i => <NarrativeChangeRow key={i.narrative_id} item={i} />)}</ul>
            {q.data.items.length > FIRST && <>
              <CollapsibleContent><ul className="divide-y border-t">{q.data.items.slice(FIRST).map(i => <NarrativeChangeRow key={i.narrative_id} item={i} />)}</ul></CollapsibleContent>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="group text-muted-foreground">
                  <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />
                  <span className="group-data-[state=open]:hidden">{q.data.items.length - FIRST}편 더 보기</span>
                  <span className="hidden group-data-[state=open]:inline">접기</span>
                </Button>
              </CollapsibleTrigger>
            </>}
          </Collapsible>}
    </div>
  </Card>
}
