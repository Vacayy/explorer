import { useState } from "react"
import { Link } from "react-router-dom"
import { Check, ChevronDown, Inbox, X } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

/**
 * 승인 대기 — 기계의 제안이 사람의 결정을 기다리는 곳 (판단 루프 ③).
 * 홈에서 바로 훑고 인라인으로 승인/거부. 유형 확장: alias → knowledge 승격(K0) → …
 */

interface ApprovalItem {
  kind: string
  id: number
  title: string
  detail: string | null
  entity_name: string | null
  stock_code: string | null
}

const VISIBLE = 5

// 에이전트 제안함 kind (진화계획 3단계 v1, docs/specs/agent-proposals.md)
const AGENT_KINDS = new Set(["neglect", "contested_edge", "devils_advocate", "falsifier_watch"])
const KIND_LABEL: Record<string, string> = {
  alias: "별칭", knowledge: "지식",
  neglect: "소외", contested_edge: "상충", devils_advocate: "질문", falsifier_watch: "반증",
}
// 확인만 하는 kind — 승인 버튼 라벨을 다르게 (액션이 없음을 정직하게)
const ACK_ONLY = new Set(["devils_advocate", "falsifier_watch"])

export default function ApprovalsCard() {
  const qc = useQueryClient()
  const [showAll, setShowAll] = useState(false)
  const { data: items = [] } = useQuery(
    apiQuery<ApprovalItem[]>({ key: ["spine", "approvals"], url: "/api/spine/approvals", staleTime: STALE.short }),
  )

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["spine", "approvals"] })
    qc.invalidateQueries({ queryKey: ["spine", "keywords"] })
    qc.invalidateQueries({ queryKey: ["spine", "feed"] })
  }
  const approve = useMutation({
    mutationFn: async (item: ApprovalItem) => {
      if (item.kind === "knowledge") {
        return (await api.post(`/api/spine/knowledge/items/${item.id}/approve`)).data as { epistemic_status: string }
      }
      if (AGENT_KINDS.has(item.kind)) {
        return (await api.post(`/api/spine/agent-proposals/${item.id}/approve`)).data as { kind: string; result: { verdict?: string; brief_status?: string } | null }
      }
      return (await api.post(`/api/spine/keywords/${item.id}/approve`)).data as { keyword: string; retro_linked_docs: number }
    },
    onSuccess: (d, item) => {
      if (item.kind === "knowledge") {
        const epi = (d as { epistemic_status: string }).epistemic_status
        toast.success(`지식 승격 — ${epi === "corroborated" ? "교차확인됨(corroborated)" : "관측(observed)"}으로 활성화`)
      } else if (AGENT_KINDS.has(item.kind)) {
        const r = d as { result: { verdict?: string; brief_status?: string } | null }
        if (item.kind === "neglect") toast.success(`리서치 실행 — 브리프 ${r.result?.brief_status ?? "완료"}`)
        else if (item.kind === "contested_edge") toast.success(`상충 조정 — 판정: ${r.result?.verdict ?? "완료"}`)
        else toast.success("확인 완료")
      } else {
        const r = d as { keyword: string; retro_linked_docs: number }
        toast.success(`'${r.keyword}' 승인 — 기존 문서 ${r.retro_linked_docs}건 소급 링크`)
      }
      invalidate()
    },
  })
  const reject = useMutation({
    mutationFn: async (item: ApprovalItem) => {
      if (item.kind === "knowledge") return api.post(`/api/spine/knowledge/items/${item.id}/reject`)
      if (AGENT_KINDS.has(item.kind)) return api.post(`/api/spine/agent-proposals/${item.id}/dismiss`)
      return api.delete(`/api/spine/keywords/${item.id}`)
    },
    onSuccess: () => {
      toast.success("거부 — 제안이 제거되었습니다")
      invalidate()
    },
  })

  if (items.length === 0) return null
  const visible = showAll ? items : items.slice(0, VISIBLE)

  return (
    <Card className="border-l-2 border-l-hypothesis">
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <Inbox className="h-4 w-4 text-hypothesis" />
        <CardTitle className="text-sm">승인 대기</CardTitle>
        <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">{items.length}</Badge>
        <span className="ml-auto text-[11px] text-muted-foreground">기계의 제안 — 결정은 사람이</span>
      </CardHeader>
      <CardContent className="divide-y">
        {visible.map((it) => (
          <div key={`${it.kind}-${it.id}`} className="flex items-center gap-2 py-1.5">
            <Badge variant="secondary" className="text-[9px] shrink-0">
              {KIND_LABEL[it.kind] ?? it.kind}
            </Badge>
            <span className="text-sm truncate" title={it.detail ?? undefined}>
              {it.stock_code ? (
                <Link to={`/analyze/${it.stock_code}/summary`} className="hover:underline">{it.title}</Link>
              ) : it.title}
              {it.kind === "knowledge" && it.detail && (
                <span className="ml-1.5 text-[10px] text-muted-foreground">{it.detail}</span>
              )}
            </span>
            <span className="ml-auto flex gap-1 shrink-0">
              <Button size="xs" variant="outline" className="h-6 px-2 text-emerald-600 hover:text-emerald-700"
                disabled={approve.isPending} onClick={() => approve.mutate(it)}>
                <Check className="h-3 w-3" /> {ACK_ONLY.has(it.kind) ? "확인" : "승인"}
              </Button>
              <Button size="xs" variant="ghost" className="h-6 px-2 text-muted-foreground hover:text-destructive"
                disabled={reject.isPending} onClick={() => reject.mutate(it)}>
                <X className="h-3 w-3" /> 거부
              </Button>
            </span>
          </div>
        ))}
        {items.length > VISIBLE && (
          <button onClick={() => setShowAll(!showAll)}
            className="flex items-center gap-1 pt-2 text-[11px] text-muted-foreground hover:text-foreground">
            <ChevronDown className={`h-3 w-3 transition-transform ${showAll ? "rotate-180" : ""}`} />
            {showAll ? "접기" : `${items.length - VISIBLE}건 더 보기`}
          </button>
        )}
      </CardContent>
    </Card>
  )
}
