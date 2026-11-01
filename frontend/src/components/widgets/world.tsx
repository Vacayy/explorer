import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { ContestedRow } from "@/components/world/ContestedPremises"
import { useBigPicture, useContestedPremises, useMyStockNarratives, useNarrativeChanges } from "@/hooks/useWorld"
import { cn } from "@/lib/utils"
import { dbAgeDays, formatDbRelative } from "@/utils/format"
import type { WorldNarrativeChange } from "@/types"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/**
 * 월드모델 위젯 (docs/specs/world-model.md §5, home-widgets.md §2 계약). 전부 /api/spine/world/* 저장분 GET만 읽는다 —
 * 서사·세계관 GET 중 일부는 묵으면 화면이 생성을 요청하므로(상세·지식 화면) 위젯은 그 경로를 쓰지 않는다.
 */

const asOf = (v: string | null | undefined) => (v ? formatDbRelative(v) : null)
const KIND_LABEL: Record<string, string> = { portfolio: "보유", watch: "관심" }

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

/* ── 이번 주 큰 그림 ── */
function useBigMeta(): WidgetMeta {
  const q = useBigPicture()
  return { asOf: asOf(q.data?.as_of), stale: !!q.data?.worldview?.stale }
}
function BigBody({ h }: WidgetBodyProps) {
  const q = useBigPicture()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const { mega, worldview } = q.data
  if (!mega.length && !worldview?.briefing) return <WidgetState empty emptyText="아직 엮인 서사가 없어요. 주 1회 만들어집니다." />
  const first = (worldview?.briefing ?? "").replace(/^#+.*$/gm, "").replace(/[*_`>-]/g, "").trim().split(/(?<=[.다])\s/)[0]
  return <div className="flex h-full flex-col gap-2">
    {q.data.worldview?.stale && <p className="text-[11px] text-chart-warning">세계관 브리핑 이후 지식·관측이 바뀌었어요.</p>}
    <ul className="min-h-0 space-y-2 overflow-y-auto">
      {mega.slice(0, h <= 2 ? 1 : 3).map(m => <li key={m.id} className="space-y-1">
        <p className={cn("text-sm font-semibold leading-snug", h <= 2 ? "line-clamp-1" : "line-clamp-2")}>{m.title ?? m.name}</p>
        {h > 2 && <div className="flex flex-wrap gap-1">{m.members.map(t => <Badge key={t} asChild variant="secondary" className="text-[10px]">
          <Link to={`/narrative?topic=${encodeURIComponent(t)}`}>{t}</Link></Badge>)}</div>}
      </li>)}
    </ul>
    {h >= 4 && first && <p className="line-clamp-2 border-t pt-2 text-[13px] text-muted-foreground"><span className="text-hypothesis">세계관 </span>{first}</p>}
  </div>
}

/* ── 흔들리는 전제 ── */
function useContestedMeta(): WidgetMeta {
  const q = useContestedPremises()
  return { asOf: asOf(q.data?.as_of) }
}
function ContestedBody({ h }: WidgetBodyProps) {
  const q = useContestedPremises()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const items = q.data.items
  if (!items.length) return <WidgetState empty emptyText="지금 충돌 중인 전제는 없어요." />
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${items.length}건`} aside={<span className="text-sm text-muted-foreground">반례가 들어온 검증 지식</span>} />
    {h <= 2
      ? <p className="line-clamp-1 text-[13px] text-muted-foreground">{items[0].statement}</p>
      : <ul className="min-h-0 space-y-2 overflow-y-auto">{items.slice(0, h).map(k => <ContestedRow key={k.id} k={k} clamp={1} />)}</ul>}
  </div>
}

/* ── 내 종목을 움직이는 서사 ── */
function useMyStocksMeta(): WidgetMeta {
  const q = useMyStockNarratives()
  return { asOf: asOf(q.data?.as_of) }
}
function MyStocksBody({ h }: WidgetBodyProps) {
  const q = useMyStockNarratives()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const { stocks, members, covered } = q.data
  if (!members) return <WidgetState empty emptyText="종목 묶음을 만들면 내 종목이 걸린 서사가 여기 보여요." />
  if (!stocks.length) return <WidgetState empty emptyText={`묶음 종목 ${members}개 중 출처가 확인된 인과 고리로 서사에 걸린 종목이 아직 없어요.`} />
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${covered}/${members}`} aside={<span className="text-sm text-muted-foreground">서사가 걸린 묶음 종목</span>} />
    {h <= 2
      ? <p className="truncate text-[13px] text-muted-foreground">{stocks[0].name} · {stocks[0].narratives.map(n => n.topic).join(", ")}</p>
      : <ul className="min-h-0 space-y-2.5 overflow-y-auto">{stocks.map(s => <li key={s.stock_code} className="space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Link to={`/analyze/${s.stock_code}/summary`} className="text-sm font-medium hover:underline">{s.name ?? s.stock_code}</Link>
            <span className="text-[10px] text-muted-foreground">{s.kinds.map(k => KIND_LABEL[k] ?? k).join("·")}</span>
            {s.narratives.map(n => <Badge key={n.topic} asChild variant="outline" className="text-[10px]">
              <Link to={`/narrative?topic=${encodeURIComponent(n.topic)}`} title={n.title ?? undefined}>{n.topic}</Link></Badge>)}
          </div>
          {h >= 4 && s.latest_drift && <p className="line-clamp-2 text-xs"><span className="text-hypothesis">바뀐 것 </span><span className="text-muted-foreground">{s.latest_drift}</span></p>}
        </li>)}</ul>}
  </div>
}

/** 월드모델 위젯 — registry.tsx가 이 배열을 그대로 펼친다 */
export const WORLD_WIDGETS: WidgetDef[] = [
  { id: "world.changes", title: "이번 주 바뀐 서사", description: "최근 7일 새 버전 · 서사가 어떻게 옮겨 갔는지 한두 문장", section: "world", group: "지금",
    size: { w: 6, h: 4, minW: 4, minH: 2 }, detailPath: "/narrative", useMeta: useChangesMeta, Body: ChangesBody },
  { id: "world.big", title: "이번 주 큰 그림", description: "여러 서사를 관통하는 엮인 서사 · 세계관 브리핑", section: "world", group: "지금",
    size: { w: 6, h: 3, minW: 4, minH: 2 }, detailPath: "/narrative", useMeta: useBigMeta, Body: BigBody },
  { id: "world.mystocks", title: "내 종목을 움직이는 서사", description: "보유·관심 종목이 걸린 서사와 이번에 바뀐 것", section: "world", group: "지금",
    size: { w: 6, h: 4, minW: 4, minH: 2 }, detailPath: "/narrative", useMeta: useMyStocksMeta, Body: MyStocksBody },
  { id: "world.contested", title: "흔들리는 전제", description: "검증된 지식 중 반례가 들어와 충돌 중인 것", section: "world", group: "그래프",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/knowledge", useMeta: useContestedMeta, Body: ContestedBody },
]
