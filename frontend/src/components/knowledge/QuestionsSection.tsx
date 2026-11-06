import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Check, ChevronDown, ChevronRight, FileText, HelpCircle, Loader2, RefreshCw, Trash2, X } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import api from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { BoundedArea } from "@/components/shared/Bounded"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { EmptyState } from "@/components/shared/ErrorState"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { MetricHint } from "@/components/shared/MetricHint"
import { InfoTip } from "@/components/shared/InfoTip"
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
  /** 전체 관측 수(observations는 최근 6건만) */
  obs_count?: number
}
interface QSub { id: number; text: string; falsifier: string | null; verdict: string | null; proxies: QProxy[] }
/** rel = '수혜'|'피해'(LLM 원문) — 화면도 같은 말(D-307, lib/judgment scenarioSide) */
export interface QScenario { event: string; answer: string; beneficiaries: { name?: string; reason?: string; rel?: string; stock_code?: string | null }[]; created_at: string }
export interface QTree {
  id: number; text: string; lead_verdict: string | null; confirm_verdict: string | null
  created_at?: string; updated_at?: string; created_by?: string
  divergence: string | null; verdict_summary: string | null; sub_questions: QSub[]
  scenario?: QScenario | null; source_doc?: { id: number; title: string | null; source_type: string } | null
}
export interface QListItem {
  id: number; text: string; status: string; lead_verdict: string | null; confirm_verdict: string | null
  divergence: string | null; verdict_summary: string | null; sub_count: number; updated_at: string
  conviction: number | null; created_by: string; source_doc_id: number | null; stock_code: string | null
}

/** 질문의 출처 — 보유 논지·관심 이유·논지 감사·서사 도출이 모두 같은 질문 객체다 (world-model.md §4) */
export const QUESTION_ORIGIN: Record<string, { label: string; cls: string }> = {
  portfolio: { label: "보유 논지", cls: "text-ink-2 border-line-2" },
  watch: { label: "관심 이유", cls: "text-ink-2 border-line-2" },
  thesis: { label: "논지 감사", cls: "text-hyp border-hyp/40" },
  system: { label: "서사 도출", cls: "text-hyp border-hyp/40" },
  digest: { label: "언급", cls: "text-ink-2 border-line-2" },
  user: { label: "직접 입력", cls: "text-ink-2 border-line-2" },
}
/** 시안 Questions 태그: 22px · 모서리 6 · 12px 500 */
const TAG = "inline-flex h-[22px] items-center rounded-md px-2 text-xs font-medium whitespace-nowrap"

/* 원장 렌즈 (#3, D-082) — 괴리(선행/확정 어긋남) 우선, 그다음 확신 순. 최근순은 updated_at 유지. */
const DIVERGING = (d: string | null) => d === "lead_ahead" || d === "confirm_ahead"
function ledgerSort(a: QListItem, b: QListItem) {
  const da = DIVERGING(a.divergence) ? 1 : 0
  const db = DIVERGING(b.divergence) ? 1 : 0
  if (da !== db) return db - da
  return (b.conviction ?? 0) - (a.conviction ?? 0)
}

export const VERDICT: Record<string, { label: string; cls: string }> = {
  leaning_yes: { label: "긍정", cls: "bg-up-tint text-up-ink" },
  leaning_no: { label: "부정", cls: "bg-down-tint text-down-ink" },
  mixed: { label: "혼조", cls: "bg-chip text-ink-2" },
  unknown: { label: "미판정", cls: "bg-chip text-ink-3" },
}
export const DIVERGENCE: Record<string, string> = {
  lead_ahead: "여론이 실적보다 앞섬 — 선행 경고",
  confirm_ahead: "실적이 여론보다 강함 — 뒤늦은 여론",
}
const MODALITY: Record<string, string> = { numeric: "수치", sentiment: "여론", stance: "태세" }
const DIR: Record<string, string> = { up: "↑", down: "↓", flat: "→" }

const listKey = ["spine", "questions", "list"]

export function VerdictBadge({ v, prefix }: { v: string | null; prefix: string }) {
  const d = VERDICT[v ?? "unknown"]
  return (
    <span className={cn("inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-md px-2 text-xs font-medium", d.cls)}>
      {prefix}{d.label}
    </span>
  )
}

export function QuestionsSection() {
  const qc = useQueryClient()
  const [sort, setSort] = useState<"ledger" | "recent">("ledger")
  const { data: all = [], isLoading } = useQuery(
    apiQuery<QListItem[]>({ key: listKey, url: "/api/spine/questions", staleTime: STALE.short }),
  )
  const filtered = all.filter((q) => q.status !== "proposed")   // proposed는 제안 큐에서 별도 처리
  const data = sort === "ledger" ? [...filtered].sort(ledgerSort) : filtered
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: listKey })
    qc.invalidateQueries({ queryKey: ["spine", "questions", "proposed"] })
  }

  return (
    <Card className="max-sm:[--card-spacing:--spacing(3)]">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-baseline gap-2.5">
          <CardTitle className="text-[15px] font-semibold">미결 질문</CardTitle>
          {!isLoading && (
            <span className="text-xs tabular-nums text-ink-3">
              {all.length}개 · 추적 {filtered.length} · 후보 {all.length - filtered.length}
            </span>
          )}
          <InfoTip label="미결 질문 설명">분할정복으로 추적하는 열린 질문입니다. 서브질문·프록시로 쪼개 선행(여론)과 확정(실적) 두 층으로 판정하고, 판정되면 지식으로 올립니다.</InfoTip>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <QuestionConsole onDone={invalidate} />
        <ProposedQueue onDone={invalidate} />
        {isLoading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
            <Loader2 className="h-3 w-3 animate-spin" /> 질문 불러오는 중…
          </div>
        ) : data.length === 0 ? (
          <EmptyState message="아직 추적 중인 질문이 없습니다. 위에 핵심 질문을 넣으면 서브질문·프록시로 분해해 추적합니다." />
        ) : (
          <div>
            <LedgerBar data={data} sort={sort} onSort={setSort} />
            {/* 질문 목록은 상한(lg) 안에서 스크롤 — 정렬을 바꿔도 카드 높이 그대로 */}
            <BoundedArea size="lg" className="mt-3"><div>{data.map((q) => <QuestionCard key={q.id} item={q} onChange={invalidate} />)}</div></BoundedArea>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* 컨빅션 원장 바 (#3, D-082) — 정렬 토글 + 의사결정 요약(괴리·고확신·논지발). 새 표면 없이 렌즈만. */
function LedgerBar({ data, sort, onSort }: {
  data: QListItem[]; sort: "ledger" | "recent"; onSort: (s: "ledger" | "recent") => void
}) {
  const diverging = data.filter((q) => DIVERGING(q.divergence)).length
  const highConv = data.filter((q) => (q.conviction ?? 0) >= 0.5).length
  const fromThesis = data.filter((q) => q.created_by === "thesis").length
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SegmentTabs
        tabs={[{ value: "ledger", label: "중요도순" }, { value: "recent", label: "최근" }]}
        value={sort} onChange={(v) => onSort(v as "ledger" | "recent")}
      />
      <MetricHint hint={
`각 질문은 두 종류의 신호로 지켜봐요.
· 여론 — 시장 분위기·심리 (빨리 움직여요)
· 실적 — 실제 숫자·성과 (늦게 확인돼요)

[중요도순] 여론과 실적이 서로 엇갈리는 질문(무언가 바뀌고 있다는 조기 신호)을 맨 위로, 그다음 근거가 탄탄한 순으로 보여줘요.
[최근] 판정이 마지막으로 갱신된 순서예요.

위쪽 요약 숫자
· 괴리 — 여론과 실적이 엇갈린 질문 수
· 고확신 — 근거가 탄탄한 질문 수
· 논지발 — 내 투자 논지를 검토해 추적을 시작한 질문 수

지금 기준
· 괴리 = 여론 신호와 실적 신호의 방향이 서로 다름
· 고확신 = 서로 다른 출처의 근거 2개 이상이 뒷받침하고, 반박은 적음`
      }>
        <HelpCircle className="h-3.5 w-3.5 text-muted-foreground/60" />
      </MetricHint>
      <div className="ml-auto flex items-center gap-2.5 text-[11px] text-muted-foreground tabular-nums">
        {diverging > 0 && <span className="text-hypothesis">괴리 {diverging}</span>}
        {highConv > 0 && <span>고확신 {highConv}</span>}
        {fromThesis > 0 && <span className="text-hypothesis">논지발 {fromThesis}</span>}
      </div>
    </div>
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
        rows={2} className="min-h-[56px] resize-none rounded-xl border-line-2 bg-card text-sm"
      />
      {ask.isPending && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 서브질문·프록시로 분해하고 컨콜에서 관측을 뽑는 중… (수 분)
        </div>
      )}
      <div>
        <Button size="sm" disabled={!text.trim() || ask.isPending} onClick={() => ask.mutate()}>
          {ask.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          추적 시작
        </Button>
      </div>
    </div>
  )
}

/* 제안 큐 (생성자 ①) — 지배 내러티브에서 자동 도출된 질문 후보. 승인 시 분해·추적(비싼 노동 뒤로, D-020) */
function ProposedQueue({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const proposedKey = ["spine", "questions", "proposed"]
  const { data = [] } = useQuery(
    apiQuery<QListItem[]>({ key: proposedKey, url: "/api/spine/questions?status=proposed", staleTime: STALE.short }),
  )
  const refresh = () => { qc.invalidateQueries({ queryKey: proposedKey }); onDone() }
  const [open, setOpen] = useState(false)   // 시안: '질문 후보 · n' 접힌 칩 — 눌러 펼침

  const propose = useMutation({
    mutationFn: () => api.post<{ proposed: number }>("/api/spine/questions/propose"),
    onSuccess: (r) => {
      const n = r.data.proposed
      toast.success(n ? `지배 내러티브에서 질문 후보 ${n}개 도출` : "새 후보 없음 — 이미 다 제안됨")
      refresh()
    },
  })
  const approve = useMutation({
    mutationFn: (id: number) => api.post(`/api/spine/questions/${id}/approve`),
    onSuccess: () => { toast.success("승인 — 분해·추적 시작"); refresh() },
    onError: () => toast.error("분해 실패 — 다시 시도"),
  })
  const reject = useMutation({
    mutationFn: (id: number) => api.delete(`/api/spine/questions/${id}`),
    onSuccess: () => { toast.success("후보 제거"); refresh() },
  })

  return (
    // 펼친 후보 목록은 칩 아래에 겹쳐 연다(Popover) — 아래 질문 목록이 밀리지 않게, 길면 안에서 스크롤
    <Popover open={open} onOpenChange={setOpen}><div className="border border-dashed border-line-2">
      <div className="flex items-center justify-between gap-2 px-3 py-1.5">
        <PopoverTrigger className="group/pq flex min-h-8 min-w-0 items-center gap-1.5 text-left text-[13px]" disabled={!data.length}>
          <span className="min-w-0 truncate">질문 후보 · 내러티브·언급 다이제스트 발</span>
          <span className="inline-flex h-[22px] items-center rounded-md px-2 text-xs font-medium whitespace-nowrap bg-chip text-ink-2 tabular-nums">{data.length}</span>
          {data.length > 0 && <ChevronDown aria-hidden className="size-3.5 shrink-0 text-ink-3 transition-transform group-data-[state=open]/pq:rotate-180" />}
        </PopoverTrigger>
        <Button size="sm" variant="ghost" className="shrink-0 text-ink-2" disabled={propose.isPending} onClick={() => propose.mutate()}>
          {propose.isPending && <Loader2 className="h-3 w-3 animate-spin" />}후보 찾기
        </Button>
      </div>
      {approve.isPending && (
        <div role="status" className="flex items-center gap-2 px-3 pb-2 text-xs text-ink-3">
          <Loader2 className="h-3 w-3 animate-spin" /> 승인된 질문을 분해·추적하는 중… (수 분)
        </div>
      )}
      <PopoverContent align="start" className="w-[min(640px,calc(100vw-32px))] p-0">
        <BoundedArea size="sm" viewportClassName="px-3 py-1.5">
        {data.map((q) => (
          <div key={q.id} className="flex items-center gap-2 py-0.5">
            <span className="text-[13px] flex-1 max-md:line-clamp-2 md:truncate">
              {q.created_by === "digest" && <span className="mr-1 align-middle text-[11px] text-ink-3">언급</span>}
              {q.text}
            </span>
            <span className="flex shrink-0 gap-1">
              <Button size="xs" variant="outline" className="h-8 px-2 text-fact md:h-6 hover:text-fact/80"
                disabled={approve.isPending} onClick={() => approve.mutate(q.id)}>
                <Check className="h-3 w-3" /> 승인
              </Button>
              <Button size="xs" variant="ghost" aria-label="후보 빼기" className="h-8 px-2 text-muted-foreground hover:text-destructive md:h-6"
                onClick={() => reject.mutate(q.id)}>
                <X className="h-3 w-3" />
              </Button>
            </span>
          </div>
        ))}
        </BoundedArea>
      </PopoverContent>
    </div></Popover>
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
    <article className="flex flex-col gap-2.5 border-t py-4">
      <div className="flex items-start gap-2">
        <Link to={`/question/${item.id}`} className="flex-1 text-[15px] font-semibold leading-[1.45] hover:underline">
          {item.text}
        </Link>
        <span className="flex shrink-0 items-center">
          <Button variant="ghost" size="icon-xs" className="text-ink-3 max-md:size-9" title="판정 재계산" aria-label="판정 재계산"
            disabled={roll.isPending} onClick={() => roll.mutate()}>
            <RefreshCw className={cn("size-3.5", roll.isPending && "animate-spin")} />
          </Button>
          <Button variant="ghost" size="icon-xs" className="text-ink-3 hover:text-destructive max-md:size-9" title="제거" aria-label="질문 제거"
            onClick={() => del.mutate()}>
            <Trash2 className="size-3.5" />
          </Button>
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <VerdictBadge v={item.confirm_verdict} prefix="확정 " />
        <VerdictBadge v={item.lead_verdict} prefix="선행 " />
        {div && <span className={cn(TAG, item.divergence === "confirm_ahead" ? "bg-fact-tint text-fact" : "bg-hyp-tint text-hyp")}>{div}</span>}
        {QUESTION_ORIGIN[item.created_by] && (
          <span className={cn(TAG, "border", QUESTION_ORIGIN[item.created_by].cls)}>{QUESTION_ORIGIN[item.created_by].label}</span>
        )}
        {item.stock_code && <Link to={`/analyze/${item.stock_code}/summary`} className={cn(TAG, "border border-line-2 font-mono text-ink-2 hover:text-ink")}>{item.stock_code}</Link>}
        <span className={cn(TAG, "border border-line-2 tabular-nums text-ink-2")}>서브질문 {item.sub_count}</span>
      </div>

      {item.verdict_summary && (
        <p className="bg-surface-2 px-3 py-2.5 text-[13px] leading-relaxed text-ink-2 line-clamp-3">{item.verdict_summary}</p>
      )}

      {/* 깊은 세부 — 목록 안에서 펼치지 않고 옆 시트로(높이 상한과 넘침) */}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger className="flex min-h-8 items-center gap-1 self-start text-xs text-ink-3 hover:text-ink">
          <ChevronRight className="h-3 w-3" />
          분해 구조 · 관측
        </SheetTrigger>
        <SheetContent side="right" className="w-full gap-0 sm:max-w-xl">
          <SheetHeader className="border-b"><SheetTitle className="pr-8 leading-snug">{item.text}</SheetTitle><SheetDescription>분해 구조 · 관측</SheetDescription></SheetHeader>
          <ScrollArea className="min-h-0 flex-1" viewportClassName="[&>div]:!block"><div className="px-4 pb-6">{open && <QuestionTree id={item.id} />}</div></ScrollArea>
        </SheetContent>
      </Sheet>
    </article>
  )
}

export function QuestionTree({ id }: { id: number }) {
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
        <div key={sq.id} className="rounded-card border px-3 py-2 space-y-1.5">
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
            {sq.proxies.map((p) => <ProxyRow key={p.id} p={p} />)}
          </div>
        </div>
      ))}
    </div>
  )
}

/* 프록시 행 — 클릭 시 디테일 모달(무엇을 측정·'예' 방향·전체 관측 시계열·출처). 트리에선 최신 1건만. */
function ProxyRow({ p }: { p: QProxy }) {
  const o = p.observations[0]
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button className="w-full flex items-center gap-1.5 text-[11px] text-left rounded px-1 -mx-1 hover:bg-muted/60 transition-colors">
          <Badge variant="secondary" className="text-[9px] shrink-0">{MODALITY[p.modality] ?? p.modality}</Badge>
          <span className="shrink-0 text-muted-foreground max-md:min-w-0 max-md:shrink max-md:truncate">{p.label}</span>
          {o ? (
            <span className="ml-auto flex items-center gap-1.5 text-right text-muted-foreground min-w-0 max-md:shrink-0">
              {/* 모바일: 관측값 원문은 접고(모달에서 열람) 프록시명·방향·날짜만 */}
              <span className="truncate max-w-[20rem] max-md:hidden" title={o.value_text ?? ""}>{o.value_text}</span>
              {o.direction && <span className="shrink-0 tabular-nums">{DIR[o.direction] ?? o.direction}</span>}
              <span className="shrink-0 tabular-nums text-[10px]">{o.observed_at?.slice(0, 10)}</span>
              {p.obs_count != null && <span className="shrink-0 tabular-nums text-[10px] max-md:hidden">{p.obs_count}건</span>}
            </span>
          ) : (
            <span className="ml-auto text-[10px] text-muted-foreground/60">관측 대기{p.tickers ? ` · ${p.tickers}` : ""}</span>
          )}
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <ProxyDetailBody proxyId={p.id} />
      </DialogContent>
    </Dialog>
  )
}

interface ProxyObs {
  observed_at: string | null; value_num: number | null; value_text: string | null
  direction: string | null; confidence: number | null; source: { doc_id: number | null; label: string } | null
}
export interface ProxyDetail {
  id: number; label: string; modality: string; yes_direction: string | null; unit: string | null
  tickers: string | null; extract_hint: string | null; sub_question_text: string | null
  question_id: number | null; question_text: string | null; observations: ProxyObs[]
}

function ProxyDetailBody({ proxyId }: { proxyId: number }) {
  const { data, isLoading } = useQuery(
    apiQuery<ProxyDetail>({ key: ["spine", "proxy", proxyId], url: `/api/spine/questions/proxy/${proxyId}`, staleTime: STALE.short }),
  )
  if (isLoading) return <div className="py-10 flex justify-center"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
  if (!data) return null
  const yesText = data.yes_direction === "up" ? "늘어남 ↑" : data.yes_direction === "down" ? "줄어듦 ↓" : "—"
  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-1.5 text-base">
          <Badge variant="secondary" className="text-[10px]">{MODALITY[data.modality] ?? data.modality}</Badge>
          {data.label}
        </DialogTitle>
        {data.sub_question_text && (
          <DialogDescription>지켜보는 하위 질문 — {data.sub_question_text}</DialogDescription>
        )}
      </DialogHeader>
      <div className="space-y-3 text-xs">
        <div className="rounded-md bg-muted/40 px-3 py-2 space-y-1">
          {data.extract_hint && <p><span className="text-muted-foreground">무엇을 보나</span> · {data.extract_hint}</p>}
          <p><span className="text-muted-foreground">'예'로 볼 방향</span> · {yesText}{data.unit ? ` (단위 ${data.unit})` : ""}</p>
          {data.tickers && <p><span className="text-muted-foreground">대상</span> · {data.tickers}</p>}
        </div>
        <div>
          <p className="text-[11px] font-medium text-muted-foreground mb-1.5">관측 기록 ({data.observations.length})</p>
          {data.observations.length === 0 ? (
            <p className="text-[11px] text-muted-foreground/60">
              아직 관측이 없어요 — {data.modality === "numeric" ? "새 실적 발표(컨콜)를 기다리는 중" : "시장 여론 스캔을 기다리는 중"}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {data.observations.map((o, i) => <ObsRow key={i} o={o} unit={data.unit} />)}
            </ul>
          )}
        </div>
      </div>
    </>
  )
}

function ObsRow({ o, unit }: { o: ProxyObs; unit: string | null }) {
  return (
    <li className="flex items-start gap-2 rounded-card border px-2.5 py-1.5">
      <span className="shrink-0 tabular-nums text-[10px] text-muted-foreground mt-0.5">{o.observed_at?.slice(0, 10)}</span>
      <span className="shrink-0 tabular-nums w-3 text-center">{o.direction ? (DIR[o.direction] ?? "") : ""}</span>
      <div className="min-w-0 flex-1">
        {o.value_num != null && <span className="font-medium tabular-nums">{o.value_num}{unit ? ` ${unit}` : ""} </span>}
        {o.value_text && <span className="text-muted-foreground">{o.value_text}</span>}
        {o.source && (
          o.source.doc_id != null ? (
            <Link to={`/doc/${o.source.doc_id}`} className="ml-1 inline-flex items-center gap-0.5 text-[10px] text-primary hover:underline align-baseline">
              <FileText className="h-2.5 w-2.5" />{o.source.label}
            </Link>
          ) : (
            <span className="ml-1 text-[10px] text-muted-foreground/70">· {o.source.label}</span>
          )
        )}
      </div>
    </li>
  )
}
