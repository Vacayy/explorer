import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { useNarrativeChanges } from "@/hooks/useWorld"
import { dbAgeDays } from "@/utils/format"
import type { WorldNarrativeChange } from "@/types"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/**
 * 월드모델 위젯 (docs/specs/world-model.md §5, home-widgets.md §2 계약). 전부 /api/spine/world/* 저장분 GET만 읽는다 —
 * 서사·세계관 GET 중 일부는 묵으면 화면이 생성을 요청하므로(상세·지식 화면) 위젯은 그 경로를 쓰지 않는다.
 */


/* ── 이번 주 바뀐 서사 ── */
function useChangesMeta(): WidgetMeta {
  const q = useNarrativeChanges(7)
  // 시안 Home: 머리 오른쪽 '● n편 · 최근 7일'
  return { asOf: q.data ? `${q.data.items.length}편 · 최근 7일` : null, stale: !!q.data && dbAgeDays(q.data.as_of) > 7 }
}
/** 위젯용 한 줄(시안 Home) — 주제 칩 · 굵은 한 문장 · 고리 변화 · 버전. 변화 요약은 링크 툴팁으로, 고리 칩은 '지금' 랜딩(NarrativeChangeRow)에만 둔다 */
function ChangeRow({ item }: { item: WorldNarrativeChange }) {
  const summary = item.is_first ? "새로 생긴 서사입니다." : item.change_summary
  return <li className="grid grid-cols-[72px_minmax(0,1fr)_auto_auto] items-baseline gap-x-3 gap-y-1 border-t py-3 first:border-t-0 max-sm:grid-cols-[minmax(0,1fr)_auto]">
    <Badge className="max-w-full truncate max-sm:col-span-full">{item.topic}</Badge>
    <Link to={`/narrative?topic=${encodeURIComponent(item.topic)}`} title={summary ?? undefined} className="min-w-0 text-[14.5px] leading-[1.5] font-semibold text-pretty hover:underline">{item.title ?? item.topic}</Link>
    <span className="text-xs whitespace-nowrap text-ink-3 tabular-nums max-sm:hidden">{item.is_first ? "새 서사" : `고리 +${item.added_count} / −${item.removed_count}`}</span>
    <span className="font-mono text-[11px] text-ink-3 tabular-nums">v{item.version}</span>
  </li>
}

function ChangesBody({ h }: WidgetBodyProps) {
  const q = useNarrativeChanges(7)
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const items = q.data.items
  if (!items.length) return <WidgetState empty emptyText="최근 7일 동안 새 버전이 나온 서사가 없어요." />
  return <div className="flex h-full flex-col gap-2">
    {h <= 2
      ? <p className="truncate text-[13px] text-muted-foreground">{items[0].title ?? items[0].topic}</p>
      : <ul className="min-h-0 overflow-y-auto">{items.slice(0, h * 2).map(i => <ChangeRow key={i.narrative_id} item={i} />)}</ul>}
  </div>
}

/** 월드모델 위젯 — registry.tsx가 이 배열을 그대로 펼친다 */
export const WORLD_WIDGETS: WidgetDef[] = [
  { id: "world.changes", title: "[내러티브] 이번주 업데이트", description: "최근 7일 새 버전 · 서사가 어떻게 옮겨 갔는지 한두 문장",
    detailPath: "/narrative", useMeta: useChangesMeta, Body: ChangesBody },
]
