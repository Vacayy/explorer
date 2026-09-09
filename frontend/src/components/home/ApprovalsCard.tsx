import { Link } from "react-router-dom"
import { AlertTriangle, BookOpen, Check, Clock, FileText, FlaskConical, GitMerge, HelpCircle, Inbox, Search, Tag, X } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ProposalPanel } from "@/components/shared/ProposalPanel"

/**
 * 승인 대기 — 기계의 제안이 사람의 결정을 기다리는 곳 (판단 루프 ③).
 * kind별 개별 카드를 2열 그리드로. 카드 안이 넘치면 내부 스크롤(펼침 UI 대신).
 */

interface ApprovalItem {
  kind: string
  id: number
  title: string
  detail: string | null
  entity_name: string | null
  stock_code: string | null
}

// 에이전트 제안함 kind (진화계획 3단계 v1, docs/specs/agent-proposals.md)
const AGENT_KINDS = new Set(["neglect", "contested_edge", "devils_advocate", "falsifier_watch", "vocab_merge", "report_suggest", "entity_alias"])
// kind별 메타 + 카드 표시 순서 (에이전트 제안 먼저, 별칭·지식은 뒤)
type KindMeta = { label: string; Icon: React.ComponentType<{ className?: string }> }
const KIND_META: Record<string, KindMeta> = {
  neglect: { label: "소외", Icon: Search },
  contested_edge: { label: "상충", Icon: AlertTriangle },
  devils_advocate: { label: "질문", Icon: HelpCircle },
  falsifier_watch: { label: "반증", Icon: Clock },
  vocab_merge: { label: "통합", Icon: GitMerge },
  report_suggest: { label: "리포트", Icon: FileText },
  entity_alias: { label: "종목 별칭", Icon: Tag },
  research_candidate: { label: "리서치", Icon: FlaskConical },
  alias: { label: "별칭", Icon: Tag },
  knowledge: { label: "지식", Icon: BookOpen },
}
const KIND_ORDER = ["report_suggest", "research_candidate", "neglect", "contested_edge", "devils_advocate", "falsifier_watch", "vocab_merge", "entity_alias", "alias", "knowledge"]
const DIR_TEXT: Record<string, string> = { up: "추정치 상향 가능", down: "추정치 하향 우려", hold: "추정치 유지 전망" }
// 확인만 하는 kind — 승인 버튼 라벨을 다르게 (액션이 없음을 정직하게)
const ACK_ONLY = new Set(["devils_advocate", "falsifier_watch"])

export default function ApprovalsCard({ hideHeader }: { hideHeader?: boolean } = {}) {
  const qc = useQueryClient()
  const { data: items = [] } = useQuery(
    apiQuery<ApprovalItem[]>({ key: ["spine", "approvals"], url: "/api/spine/approvals", staleTime: STALE.short }),
  )

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["spine", "approvals"] })
    qc.invalidateQueries({ queryKey: ["spine", "keywords"] })
    qc.invalidateQueries({ queryKey: ["spine", "feed"] })
    qc.invalidateQueries({ queryKey: ["spine", "research", "candidates"] })
  }
  const approve = useMutation({
    mutationFn: async (item: ApprovalItem) => {
      if (item.kind === "knowledge") {
        return (await api.post(`/api/spine/knowledge/items/${item.id}/approve`)).data as { epistemic_status: string }
      }
      if (item.kind === "research_candidate") {
        return (await api.post(`/api/spine/research/candidates/${item.id}/approve`)).data as { revision_call: { direction: string } | null }
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
      } else if (item.kind === "research_candidate") {
        const rc = (d as { revision_call: { direction: string } | null }).revision_call
        toast.success(`리서치 완료 — ${rc ? (DIR_TEXT[rc.direction] ?? "방향 판단") : "방향 유보"}`)
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
      if (item.kind === "research_candidate") return api.post(`/api/spine/research/candidates/${item.id}/dismiss`)
      if (AGENT_KINDS.has(item.kind)) return api.post(`/api/spine/agent-proposals/${item.id}/dismiss`)
      return api.delete(`/api/spine/keywords/${item.id}`)
    },
    onSuccess: () => {
      toast.success("거부 — 제안이 제거되었습니다")
      invalidate()
    },
  })

  if (items.length === 0) return null

  // kind별로 묶어 개별 카드로. 순서는 KIND_ORDER, 미등록 kind는 뒤에.
  const kindsInOrder = [...KIND_ORDER, ...items.map((it) => it.kind).filter((k) => !KIND_ORDER.includes(k))]
  const groups = Array.from(new Set(kindsInOrder))
    .map((kind) => ({ kind, rows: items.filter((it) => it.kind === kind) }))
    .filter((g) => g.rows.length > 0)

  const renderRow = (it: ApprovalItem) => (
    <div key={`${it.kind}-${it.id}`} className="flex items-start gap-2 py-1.5">
      <span className="text-sm min-w-0 flex-1 break-words" title={it.detail ?? undefined}>
        {it.stock_code ? (
          <Link to={`/analyze/${it.stock_code}/summary`} className="hover:underline">{it.title}</Link>
        ) : it.title}
        {it.kind === "knowledge" && it.detail && (
          <span className="ml-1.5 text-[10px] text-muted-foreground">{it.detail}</span>
        )}
      </span>
      <span className="flex gap-1 shrink-0">
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
  )

  return (
    <section className="space-y-2">
      {!hideHeader && (
        <div className="flex items-center gap-2">
          <Inbox className="h-4 w-4 text-hypothesis" />
          <h3 className="text-sm font-semibold">승인 대기</h3>
          <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">{items.length}</Badge>
          <span className="ml-auto text-[11px] text-muted-foreground">기계의 제안 — 결정은 사람이</span>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 items-start">
        {groups.map((g) => {
          const meta = KIND_META[g.kind]
          const Icon = meta?.Icon ?? Inbox
          return (
            <ProposalPanel key={g.kind} icon={Icon} title={meta?.label ?? g.kind} count={g.rows.length}
              maxHeight="50vh" contentClassName="divide-y">
              {g.rows.map(renderRow)}
            </ProposalPanel>
          )
        })}
      </div>
    </section>
  )
}
