import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ChevronDown, HelpCircle, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import api from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { EmptyState } from "@/components/shared/ErrorState"
import { cn } from "@/lib/utils"

/**
 * 미결 질문 (D-067·D-068, docs/specs/question-proxy.md) — 지식의 미결층.
 * 핵심질문을 분할정복(서브질문→프록시→관측)으로 추적하고, pace layer 2층(선행/확정)으로 판정한다.
 * 판정되면 지식으로 승격(Phase 3). 지식과 인접 배치 — 지식=검증, 질문=미결.
 */

interface QObs { observed_at: string; value_num: number | null; value_text: string | null; direction: string | null }
interface QProxy {
  id: number; label: string; modality: string; unit: string | null
  yes_direction: string | null; tickers: string | null; observations: QObs[]
}
interface QSub { id: number; text: string; falsifier: string | null; verdict: string | null; proxies: QProxy[] }
interface QTree {
  id: number; text: string; lead_verdict: string | null; confirm_verdict: string | null
  divergence: string | null; verdict_summary: string | null; sub_questions: QSub[]
}
interface QListItem {
  id: number; text: string; lead_verdict: string | null; confirm_verdict: string | null
  divergence: string | null; verdict_summary: string | null; sub_count: number; updated_at: string
}

const VERDICT: Record<string, { label: string; cls: string }> = {
  leaning_yes: { label: "긍정", cls: "text-primary border-primary/40" },
  leaning_no: { label: "부정", cls: "text-destructive border-destructive/50" },
  mixed: { label: "혼조", cls: "text-hypothesis border-hypothesis/40" },
  unknown: { label: "미판정", cls: "text-muted-foreground border-border" },
}
const DIVERGENCE: Record<string, string> = {
  lead_ahead: "여론이 실적보다 앞섬 — 선행 경고",
  confirm_ahead: "실적이 여론보다 강함 — 뒤늦은 여론",
}
const MODALITY: Record<string, string> = { numeric: "수치", sentiment: "여론", stance: "태세" }
const DIR: Record<string, string> = { up: "↑", down: "↓", flat: "→" }

const listKey = ["spine", "questions", "list"]

function VerdictBadge({ v, prefix }: { v: string | null; prefix: string }) {
  const d = VERDICT[v ?? "unknown"]
  return (
    <Badge variant="outline" className={cn("text-[10px] gap-1", d.cls)}>
      <span className="text-muted-foreground font-normal">{prefix}</span>{d.label}
    </Badge>
  )
}

export function QuestionsSection() {
  const qc = useQueryClient()
  const { data = [], isLoading } = useQuery(
    apiQuery<QListItem[]>({ key: listKey, url: "/api/spine/questions", staleTime: STALE.short }),
  )
  const invalidate = () => qc.invalidateQueries({ queryKey: listKey })

  return (
    <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_5%,var(--card))]">
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <HelpCircle className="h-4 w-4 text-hypothesis" /> 미결 질문
        </CardTitle>
        <span className="text-[11px] text-muted-foreground">
          분할정복으로 추적하는 열린 질문 — 서브질문·프록시로 쪼개 선행(여론)/확정(실적) 2층으로 판정. 판정되면 지식으로
        </span>
      </CardHeader>
      <CardContent className="space-y-2">
        <QuestionConsole onDone={invalidate} />
        {isLoading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
            <Loader2 className="h-3 w-3 animate-spin" /> 질문 불러오는 중…
          </div>
        ) : data.length === 0 ? (
          <EmptyState message="아직 추적 중인 질문이 없습니다. 위에 핵심 질문을 넣으면 서브질문·프록시로 분해해 추적합니다." />
        ) : (
          <div className="space-y-2">
            {data.map((q) => <QuestionCard key={q.id} item={q} onChange={invalidate} />)}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function QuestionConsole({ onDone }: { onDone: () => void }) {
  const [text, setText] = useState("")
  const ask = useMutation({
    mutationFn: async () => (await api.post("/api/spine/questions", { text })).data as QTree,
    onSuccess: () => { toast.success("분해 완료 — 서브질문·프록시로 추적을 시작합니다"); setText(""); onDone() },
    onError: () => toast.error("분해 실패 — 다시 시도해주세요"),
  })
  return (
    <div className="space-y-2">
      <Textarea
        value={text} onChange={(e) => setText(e.target.value)}
        placeholder="예: 폭발적으로 증가하는 AI 사용량이 막대한 설비투자를 감당할 매출·마진으로 전환될 수 있는가?"
        className="min-h-[56px] text-sm"
      />
      {ask.isPending && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 서브질문·프록시로 분해하고 컨콜에서 관측을 뽑는 중… (수 분)
        </div>
      )}
      <div className="flex justify-end">
        <Button size="sm" disabled={!text.trim() || ask.isPending} onClick={() => ask.mutate()}>
          {ask.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          추적 시작
        </Button>
      </div>
    </div>
  )
}

function QuestionCard({ item, onChange }: { item: QListItem; onChange: () => void }) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const div = item.divergence && DIVERGENCE[item.divergence]

  const roll = useMutation({
    mutationFn: () => api.post(`/api/spine/questions/${item.id}/rollup`),
    onSuccess: () => {
      toast.success("판정 갱신")
      qc.invalidateQueries({ queryKey: ["spine", "questions", item.id] })
      onChange()
    },
  })
  const del = useMutation({
    mutationFn: () => api.delete(`/api/spine/questions/${item.id}`),
    onSuccess: () => { toast.success("질문 제거됨"); onChange() },
  })

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-start gap-2">
          <p className="text-sm leading-snug flex-1">{item.text}</p>
          <span className="flex shrink-0 items-center gap-1">
            <button className="text-muted-foreground/60 hover:text-foreground" title="판정 재계산"
              disabled={roll.isPending} onClick={() => roll.mutate()}>
              <RefreshCw className={cn("h-3.5 w-3.5", roll.isPending && "animate-spin")} />
            </button>
            <button className="text-muted-foreground/60 hover:text-destructive" title="제거"
              onClick={() => del.mutate()}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <VerdictBadge v={item.confirm_verdict} prefix="확정 " />
          <VerdictBadge v={item.lead_verdict} prefix="선행 " />
          {div && <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">{div}</Badge>}
          <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">서브질문 {item.sub_count}</span>
        </div>

        {item.verdict_summary && (
          <p className="text-[11px] text-muted-foreground rounded-md bg-muted/40 px-2.5 py-1.5">{item.verdict_summary}</p>
        )}

        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="group/tr flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/tr:rotate-180" />
            분해 구조 · 관측
          </CollapsibleTrigger>
          <CollapsibleContent>{open && <QuestionTree id={item.id} />}</CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

function QuestionTree({ id }: { id: number }) {
  const { data, isLoading } = useQuery(
    apiQuery<QTree>({ key: ["spine", "questions", id], url: `/api/spine/questions/${id}`, staleTime: STALE.short }),
  )
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
        <Loader2 className="h-3 w-3 animate-spin" /> 분해 구조 불러오는 중…
      </div>
    )
  }
  if (!data) return null
  return (
    <div className="mt-2 space-y-2">
      {data.sub_questions.map((sq) => (
        <div key={sq.id} className="rounded-md border px-3 py-2 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium flex-1">{sq.text}</span>
            <VerdictBadge v={sq.verdict} prefix="" />
          </div>
          {sq.falsifier && (
            <p className="text-[10px] text-muted-foreground">
              <span className="font-medium">반증조건</span> — {sq.falsifier}
            </p>
          )}
          <div className="space-y-1">
            {sq.proxies.map((p) => {
              const o = p.observations[0]
              return (
                <div key={p.id} className="flex items-center gap-1.5 text-[11px]">
                  <Badge variant="secondary" className="text-[9px] shrink-0">{MODALITY[p.modality] ?? p.modality}</Badge>
                  <span className="shrink-0 text-muted-foreground">{p.label}</span>
                  {o ? (
                    <span className="ml-auto flex items-center gap-1.5 text-right text-muted-foreground min-w-0">
                      <span className="truncate max-w-[22rem]" title={o.value_text ?? ""}>{o.value_text}</span>
                      {o.direction && <span className="shrink-0 tabular-nums">{DIR[o.direction] ?? o.direction}</span>}
                      <span className="shrink-0 tabular-nums text-[10px]">{o.observed_at?.slice(0, 10)}</span>
                    </span>
                  ) : (
                    <span className="ml-auto text-[10px] text-muted-foreground/60">관측 대기{p.tickers ? ` · ${p.tickers}` : ""}</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
