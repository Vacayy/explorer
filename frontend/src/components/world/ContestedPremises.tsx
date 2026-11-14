import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
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
