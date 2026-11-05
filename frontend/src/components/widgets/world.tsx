import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { useNarrativeChanges } from "@/hooks/useWorld"
import { dbAgeDays, formatDbRelative } from "@/utils/format"
import type { WorldNarrativeChange } from "@/types"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/**
 * 월드모델 위젯 (docs/specs/world-model.md §5, home-widgets.md §2 계약). 전부 /api/spine/world/* 저장분 GET만 읽는다 —
 * 서사·세계관 GET 중 일부는 묵으면 화면이 생성을 요청하므로(상세·지식 화면) 위젯은 그 경로를 쓰지 않는다.
 */

const asOf = (v: string | null | undefined) => (v ? formatDbRelative(v) : null)

/* ── 이번 주 바뀐 서사 ── */
function useChangesMeta(): WidgetMeta {
  const q = useNarrativeChanges(7)
  return { asOf: asOf(q.data?.as_of), stale: !!q.data && dbAgeDays(q.data.as_of) > 7 }
}
/** 위젯용 한 줄 — 제목 · 라벨 · 버전/시각 · 어떻게 옮겨 갔나 1~2문장. 고리 칩은 '지금' 랜딩(NarrativeChangeRow)에만 둔다 */
function ChangeRow({ item }: { item: WorldNarrativeChange }) {
  const summary = item.is_first ? "새로 생긴 서사입니다." : item.change_summary
  // 라벨 · 제목 · 갱신 시각 한 줄, 아래에 서사 변화 요약 전문(자르지 않는다)
  return <li className="space-y-1">
    <div className="flex items-start gap-1.5">
      <Badge variant="outline" className="mt-px max-w-[40%] shrink-0 truncate text-[10px]">{item.topic}</Badge>
      <Link to={`/narrative?topic=${encodeURIComponent(item.topic)}`} className="min-w-0 flex-1 text-sm font-semibold leading-snug hover:underline">{item.title ?? item.topic}</Link>
      <span className="mt-0.5 shrink-0 text-[11px] text-muted-foreground tabular-nums">{formatDbRelative(item.created_at)}</span>
    </div>
    {summary && <p className="text-xs leading-relaxed text-muted-foreground">{summary}</p>}
  </li>
}
function ChangesBody({ h }: WidgetBodyProps) {
  const q = useNarrativeChanges(7)
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const items = q.data.items
  if (!items.length) return <WidgetState empty emptyText="최근 7일 동안 새 버전이 나온 서사가 없어요." />
  return <div className="flex h-full flex-col gap-2">
    <p className="text-[12px] text-muted-foreground"><span className="font-medium text-foreground">{items.length}편</span> · 최근 7일 새 버전</p>
    {h <= 2
      ? <p className="truncate text-[13px] text-muted-foreground">{items[0].title ?? items[0].topic}</p>
      : <ul className="min-h-0 space-y-3 overflow-y-auto">{items.slice(0, h * 2).map(i => <ChangeRow key={i.narrative_id} item={i} />)}</ul>}
  </div>
}

/** 월드모델 위젯 — registry.tsx가 이 배열을 그대로 펼친다 */
export const WORLD_WIDGETS: WidgetDef[] = [
  { id: "world.changes", title: "이번 주 바뀐 서사", description: "최근 7일 새 버전 · 서사가 어떻게 옮겨 갔는지 한두 문장",
    detailPath: "/narrative", useMeta: useChangesMeta, Body: ChangesBody },
]
