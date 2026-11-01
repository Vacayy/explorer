import { AlertTriangle } from "lucide-react"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { proxyChange, proxyValue } from "@/components/proxy/ProxyBoardsPage"
import { useProxyBoard, useProxyBoards } from "@/hooks/useProxyBoards"
import { cn } from "@/lib/utils"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/** 프록시 보드 위젯 — 보드 하나 = 위젯 하나(D-240). params.board 없으면 첫 보드. 순수 읽기(LLM 0) */
function useBoardId(params?: Record<string, unknown>) {
  const list = useProxyBoards()
  const want = Number(params?.board)
  return { list, id: (want && list.data?.some(b => b.id === want) ? want : list.data?.[0]?.id) ?? null }
}

function useProxyMeta(): WidgetMeta {
  const { id } = useBoardId()
  const d = useProxyBoard(id)
  const dates = (d.data?.items ?? []).map(i => i.latest.as_of).filter(Boolean) as string[]
  return { asOf: dates.length ? dates.sort().at(-1)! : null }
}

function ProxyBody({ h, params }: WidgetBodyProps) {
  const { list, id } = useBoardId(params)
  const d = useProxyBoard(id)
  if (list.isPending || (id && d.isPending)) return <WidgetState loading />
  if (list.isError || d.isError) return <WidgetState error onRetry={() => { void list.refetch(); void d.refetch() }} />
  if (!id || !d.data) return <WidgetState empty emptyText="프록시 보드가 없어요. 월드모델 › 내 판단에서 만드세요." />
  const b = d.data
  const rows = [...b.items].sort((a, c) => Number(c.in_warn) - Number(a.in_warn)).slice(0, Math.max(1, h * 2 - 2))
  return <div className="flex h-full flex-col gap-2">
    <p className="text-[13px] text-muted-foreground"><span className="font-medium text-foreground">{b.name}</span> · 지표 {b.item_count}개 중 <span className={cn(b.in_warn_count && "font-medium text-chart-warning")}>{b.in_warn_count}개</span>가 주의 방향</p>
    <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rows.map(it => (
        <li key={it.proxy_id} className="flex items-center gap-2 py-1.5">
          {it.in_warn && <AlertTriangle className="size-3 shrink-0 text-chart-warning" aria-label="주의 방향" />}
          <span className="min-w-0 flex-1 truncate">{it.label}</span>
          <span className="shrink-0 tabular-nums">{proxyValue(it.latest.value, it.unit)}</span>
          <span className={cn("w-16 shrink-0 text-right text-xs tabular-nums", it.in_warn ? "text-chart-warning" : "text-muted-foreground")}>{proxyChange(it)}</span>
        </li>
      ))}
    </ul>
  </div>
}

export const PROXY_WIDGETS: WidgetDef[] = [
  { id: "world.proxyBoard", title: "프록시 보드", description: "직접 만든 지표 묶음 — 회사채·수출입·컨콜·섹터·매크로", section: "world", group: "내 판단",
    size: { w: 6, h: 4, minW: 4, minH: 2 }, detailPath: "/proxy-boards", useMeta: useProxyMeta, Body: ProxyBody },
]
