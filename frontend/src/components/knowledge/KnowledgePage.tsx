import { useState } from "react"
import { Link } from "react-router-dom"
import { Markdown } from "@/components/shared/Markdown"
import {
  BookOpenCheck, ChevronDown, Globe2, Loader2, Swords, Plus, Trash2, Check, X, Inbox,
} from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import api from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { Expandable } from "@/components/shared/Expandable"
import { PageContainer } from "@/components/shared/PageContainer"
import { KnowledgeSubNav } from "@/components/knowledge/KnowledgeSubNav"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { cn } from "@/lib/utils"

/**
 * /knowledge — 지식 체계 관측·주입 페이지 (docs/specs/knowledge-page.md).
 * 3섹션: 구조 지도(학습) · 현황 대시보드(관측) · 내 지식 주입(참여).
 * salience×conviction으로 각 지식을 위치시켜 '시장 주목 vs 진리근접도'의 갭을 드러낸다.
 */

interface KnowledgeEntity { name: string; type: string; aliases: string | null }
interface Falsifier {
  condition: string; triggered_at: string | null; triggered_doc_id: number | null
  target_entity: string | null; metric: string | null; threshold: string | null; window: string | null
}
interface KnowledgeItem {
  id: number
  statement: string
  epistemic_status: string
  pace_layer: string
  support: number
  refute: number
  independent: number
  source_types: number
  activation: number | null
  salience: number
  conviction: number
  quadrant: string
  is_mine: boolean
  rationale: string | null
  source_ref: string | null
  entities: KnowledgeEntity[]
  falsifiers: Falsifier[]
  created_at: string
  contested_at: string | null
}
interface EvidenceDoc {
  doc_id: number | null; title: string | null; source_type: string | null
  stance: string; independent: boolean; observed_at: string
}
interface Overview {
  total: number; corroborated: number; contested: number; hypothesis: number
  pending: number; mine: number; by_layer: Record<string, number>
}

const LAYER_LABEL: Record<string, string> = {
  event: "사건", flow: "흐름", cycle: "사이클", structure: "구조", regime: "체제",
}
const EPISTEMIC_LABEL: Record<string, string> = {
  observed: "관측됨", corroborated: "교차확인", contested: "충돌 중",
  hypothesis: "가설", superseded: "대체됨",
}
const QUADRANT: Record<string, { label: string; cls: string; hint: string }> = {
  hidden_edge: { label: "주목받지 않은 확신", cls: "text-primary border-primary/40", hint: "기회·소외된 엣지" },
  priced_in: { label: "주목받는 확신", cls: "text-foreground border-border", hint: "선반영·엣지 소진" },
  overhyped: { label: "확신 대비 과한 주목", cls: "text-hypothesis border-hypothesis/40", hint: "진자 경고" },
  noise: { label: "단순 노이즈", cls: "text-muted-foreground border-border", hint: "무시" },
}
const QUADRANT_FILTERS = ["hidden_edge", "overhyped", "priced_in", "noise"] as const

const itemsKey = ["spine", "knowledge", "items"]
const overviewKey = ["spine", "knowledge", "overview"]

export default function KnowledgePage() {
  const qc = useQueryClient()
  const [quadFilter, setQuadFilter] = useState<string | null>(null)
  const [mineOnly, setMineOnly] = useState(false)

  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<KnowledgeItem[]>({ key: itemsKey, url: "/api/spine/knowledge/items", staleTime: STALE.short }),
  )
  const { data: overview } = useQuery(
    apiQuery<Overview>({ key: overviewKey, url: "/api/spine/knowledge/overview", staleTime: STALE.short }),
  )

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: itemsKey })
    qc.invalidateQueries({ queryKey: overviewKey })
  }

  if (isLoading) return <KnowledgeSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const filtered = data.filter((k) =>
    (!quadFilter || k.quadrant === quadFilter) && (!mineOnly || k.is_mine))

  return (
    <PageContainer gap="sm">
      <KnowledgeSubNav />
      <div className="flex items-baseline gap-2">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <BookOpenCheck className="h-5 w-5 text-muted-foreground" /> 지식 체계
        </h2>
        <span className="text-xs text-muted-foreground">
          온톨로지(전체 인과 지도)에서 반복·독립 관측으로 검증돼 승격된 핵심 전제 — 주 1회 갱신. 시장 주목 × 근거 강도로 위치
        </span>
      </div>

      <StructureMap />
      {overview && <OverviewStrip o={overview} />}
      <InjectConsole onDone={invalidate} />
      <PendingQueue onDone={invalidate} />
      <WorldviewCard />

      {data.length === 0 ? (
        <EmptyState message="아직 승격된 지식이 없습니다. 위에서 첫 지식을 주입하거나, 수집이 쌓이면 주간 승격 배치가 후보를 만듭니다." />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-[11px] text-muted-foreground mr-0.5">위치</span>
            {QUADRANT_FILTERS.map((q) => (
              <Badge key={q} variant={quadFilter === q ? "default" : "outline"}
                className="cursor-pointer text-[10px]"
                onClick={() => setQuadFilter(quadFilter === q ? null : q)}>
                {QUADRANT[q].label}
              </Badge>
            ))}
            <Badge variant={mineOnly ? "default" : "outline"} className="cursor-pointer text-[10px] ml-1"
              onClick={() => setMineOnly(!mineOnly)}>내 지식만</Badge>
            <span className="ml-auto text-[11px] text-muted-foreground">{filtered.length}건 · 활성도 순</span>
          </div>
          <div className="space-y-2">
            {filtered.map((k) => <KnowledgeCard key={k.id} item={k} onDelete={invalidate} />)}
          </div>
        </>
      )}
    </PageContainer>
  )
}

/* ---------- 4-1. 구조 지도 (학습, LLM 0) ---------- */

function StructureMap() {
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="w-full">
          <CardHeader className="pb-2 flex-row items-center gap-2">
            <CardTitle className="text-sm">지식은 어떻게 만들어지나</CardTitle>
            <span className="text-[11px] text-muted-foreground">3계층 · 수명주기 · 시간 층</span>
            <ChevronDown className={cn("ml-auto h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="space-y-3 text-xs text-muted-foreground">
            <div>
              <p className="font-medium text-foreground mb-1">① 3계층 — 사례에서 스키마로</p>
              <p className="tabular-nums">원문서(records) → 주장(claims) → <b className="text-foreground">지식(knowledge)</b></p>
              <p>반복·독립 관측으로 개별 사례를 통합 지식으로 승격한다 (해마→신피질 공고화).</p>
            </div>
            <div>
              <p className="font-medium text-foreground mb-1">② 수명주기 — 지우지 않고 공존</p>
              <div className="flex flex-wrap items-center gap-1">
                {["관측됨", "교차확인", "충돌 중", "대체됨"].map((s, i) => (
                  <span key={s} className="flex items-center gap-1">
                    {i > 0 && <span className="text-muted-foreground/50">→</span>}
                    <Badge variant="outline" className="text-[10px]">{s}</Badge>
                  </span>
                ))}
                <span className="text-muted-foreground/50 mx-0.5">·</span>
                <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">가설(내 주입)</Badge>
              </div>
              <p className="mt-1">반례가 쌓이면 덮어쓰지 않고 <b className="text-foreground">충돌 중</b>으로 공존 — 소수의견 보존.</p>
            </div>
            <div>
              <p className="font-medium text-foreground mb-1">③ 시간 층 — 느릴수록 오래 사는 지식</p>
              <div className="flex flex-wrap items-center gap-1">
                {(["event", "flow", "cycle", "structure", "regime"] as const).map((l) => (
                  <Badge key={l} variant="secondary" className="text-[10px]">{LAYER_LABEL[l]}</Badge>
                ))}
              </div>
              <p className="mt-1">사건(빨리 잊음) → 체제(수년~십년). 지식 계층은 사이클 이하 느린 층 중심.</p>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

/* ---------- 4-2. 현황 대시보드 ---------- */

function OverviewStrip({ o }: { o: Overview }) {
  const cells: { label: string; value: number; cls?: string }[] = [
    { label: "활성 지식", value: o.total },
    { label: "교차확인", value: o.corroborated, cls: "text-primary" },
    { label: "충돌 중", value: o.contested, cls: o.contested > 0 ? "text-destructive" : undefined },
    { label: "가설", value: o.hypothesis, cls: "text-hypothesis" },
    { label: "승격 대기", value: o.pending },
    { label: "내 주입", value: o.mine },
  ]
  return (
    <Card>
      <CardContent className="py-3 grid grid-cols-3 sm:grid-cols-6 gap-2">
        {cells.map((c) => (
          <div key={c.label} className="text-center">
            <div className={cn("text-lg font-bold tabular-nums", c.cls)}>{c.value}</div>
            <div className="text-[10px] text-muted-foreground">{c.label}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

/* 승격 대기 큐 — proposed 지식 인라인 승인/거부 */
function PendingQueue({ onDone }: { onDone: () => void }) {
  const { data = [] } = useQuery(
    apiQuery<KnowledgeItem[]>({
      key: ["spine", "knowledge", "items", "proposed"],
      url: "/api/spine/knowledge/items?status=proposed", staleTime: STALE.short,
    }),
  )
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["spine", "knowledge", "items", "proposed"] })
    onDone()
  }
  const approve = useMutation({
    mutationFn: (id: number) => api.post(`/api/spine/knowledge/items/${id}/approve`),
    onSuccess: () => { toast.success("지식 승격 — 활성화됨"); refresh() },
  })
  const reject = useMutation({
    mutationFn: (id: number) => api.post(`/api/spine/knowledge/items/${id}/reject`),
    onSuccess: () => { toast.success("거부 — 후보 제거됨"); refresh() },
  })
  if (data.length === 0) return null
  return (
    <Card className="border-l-2 border-l-hypothesis">
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <Inbox className="h-4 w-4 text-hypothesis" />
        <CardTitle className="text-sm">승격 대기</CardTitle>
        <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">{data.length}</Badge>
        <span className="ml-auto text-[11px] text-muted-foreground">기계의 제안 — 결정은 사람이</span>
      </CardHeader>
      <CardContent className="divide-y">
        {data.map((k) => (
          <div key={k.id} className="flex items-center gap-2 py-1.5">
            <Badge variant="secondary" className="text-[9px] shrink-0">{LAYER_LABEL[k.pace_layer] ?? k.pace_layer}</Badge>
            <span className="text-sm truncate">{k.statement}</span>
            <span className="ml-auto flex gap-1 shrink-0">
              <Button size="xs" variant="outline" className="h-6 px-2 text-emerald-600 hover:text-emerald-700"
                disabled={approve.isPending} onClick={() => approve.mutate(k.id)}>
                <Check className="h-3 w-3" /> 승인
              </Button>
              <Button size="xs" variant="ghost" className="h-6 px-2 text-muted-foreground hover:text-destructive"
                disabled={reject.isPending} onClick={() => reject.mutate(k.id)}>
                <X className="h-3 w-3" /> 거부
              </Button>
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

interface Worldview { status: string; briefing: string | null; created_at: string | null; stale?: boolean }

/** 세계관 브리핑 — 느린 층(지식) + 빠른 층(이번 주 관측) 종합 (§G 통념 계량) */
function WorldviewCard() {
  const cached = useQuery(
    apiQuery<Worldview>({ key: ["spine", "worldview"], url: "/api/spine/knowledge/worldview", staleTime: STALE.short }),
  )
  const fresh = useQuery(
    apiComputeQuery<Worldview>({
      key: ["spine", "worldview", "compute"], url: "/api/spine/knowledge/worldview/compute",
      enabled: !!cached.data?.stale,
    }),
  )
  const w = fresh.data ?? cached.data
  if (!w || (w.status === "empty" && !w.briefing && !fresh.isFetching)) return null

  return (
    <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]">
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Globe2 className="h-4 w-4 text-hypothesis" /> 세계관 브리핑
        </CardTitle>
        <span className="text-[11px] text-muted-foreground">자리 잡은 전제 · 도전받는 것 · 이번 주</span>
        {w.created_at && (
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{w.created_at.slice(0, 10)} 기준</span>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        {fresh.isFetching && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> 지식·이번 주 관측을 반영해 갱신 중… (수십 초)
          </div>
        )}
        {w.briefing && <Expandable collapsedHeight={260}><Markdown>{w.briefing}</Markdown></Expandable>}
        {w.briefing && (
          <div className="text-right">
            <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
              AI 종합 · 지식 상태 변경 시 갱신 — 판단은 사람이
            </Badge>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 4-3. 내 지식 주입 콘솔 ---------- */

function InjectConsole({ onDone }: { onDone: () => void }) {
  const [content, setContent] = useState("")
  const [rationale, setRationale] = useState("")
  const [source, setSource] = useState("")
  const [epistemic, setEpistemic] = useState<"hypothesis" | "fact">("hypothesis")
  const [expanded, setExpanded] = useState(false)

  const inject = useMutation({
    mutationFn: async () =>
      (await api.post("/api/spine/knowledge", { content, epistemic, rationale, source })).data as {
        title: string; entities: string[]
      },
    onSuccess: (d) => {
      toast.success(
        d.entities.length
          ? `주입됨 — ${d.entities.slice(0, 3).join(", ")} 연결 · 반증 조건·근거 생성 완료`
          : "주입됨 — 시장 엔티티 연결이 없어 개인 메모로 저장",
      )
      setContent(""); setRationale(""); setSource(""); setExpanded(false)
      onDone()
    },
    onError: () => toast.error("주입 실패 — 다시 시도해주세요"),
  })

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <Plus className="h-4 w-4 text-muted-foreground" />
        <CardTitle className="text-sm">지식 주입</CardTitle>
        <span className="text-[11px] text-muted-foreground">
          내 가설을 시스템에 넣으면 기계가 지지/반증을 붙여 검증한다 — 반례가 쌓이면 충돌로 강등
        </span>
      </CardHeader>
      <CardContent className="space-y-2">
        <Textarea
          value={content} onChange={(e) => setContent(e.target.value)}
          placeholder="예: SK하이닉스는 HBM 공급을 장기계약으로 고착화해 고객 이탈 비용을 높였다"
          className="min-h-[64px] text-sm"
        />
        {expanded && (
          <div className="grid gap-2 sm:grid-cols-2">
            <Input value={rationale} onChange={(e) => setRationale(e.target.value)}
              placeholder="근거 — 왜 믿나 (선택)" className="text-sm" />
            <Input value={source} onChange={(e) => setSource(e.target.value)}
              placeholder="출처 — 누가 말했나 (선택)" className="text-sm" />
          </div>
        )}
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            <Button size="sm" variant={epistemic === "hypothesis" ? "default" : "outline"}
              onClick={() => setEpistemic("hypothesis")}>가설</Button>
            <Button size="sm" variant={epistemic === "fact" ? "default" : "outline"}
              onClick={() => setEpistemic("fact")}>사실</Button>
          </div>
          {!expanded && (
            <Button size="sm" variant="ghost" className="text-muted-foreground"
              onClick={() => setExpanded(true)}>근거·출처 추가</Button>
          )}
          <Button size="sm" className="ml-auto" disabled={!content.trim() || inject.isPending}
            onClick={() => inject.mutate()}>
            {inject.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            주입
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* ---------- 지식 카드 ---------- */

function QuadrantGlyph({ quadrant }: { quadrant: string }) {
  // 2×2: 상=주목高, 좌=확신低. topLeft=overhyped, topRight=priced_in, bottomLeft=noise, bottomRight=hidden_edge
  const cellOf = ["overhyped", "priced_in", "noise", "hidden_edge"]
  const color = QUADRANT[quadrant]?.cls.split(" ")[0] ?? "text-muted-foreground"
  return (
    <span className="inline-grid grid-cols-2 gap-0.5 shrink-0" title="주목(세로)×확신(가로)">
      {cellOf.map((c) => (
        <span key={c} className={cn("h-1.5 w-1.5 rounded-[1px]",
          c === quadrant ? cn("bg-current", color) : "bg-muted-foreground/20")} />
      ))}
    </span>
  )
}

function KnowledgeCard({ item: k, onDelete }: { item: KnowledgeItem; onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  const contested = k.epistemic_status === "contested"
  const q = QUADRANT[k.quadrant]
  const qc = useQueryClient()

  const del = useMutation({
    mutationFn: () => api.delete(`/api/spine/knowledge/items/${k.id}`),
    onSuccess: () => {
      toast.success("삭제됨 — 내 가설을 제거했습니다")
      qc.invalidateQueries({ queryKey: itemsKey })
      onDelete()
    },
    onError: () => toast.error("삭제 실패"),
  })

  return (
    <Card className={cn(contested && "border-destructive/40 border-l-2 border-l-destructive")}>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge variant="secondary" className="text-[10px]">{LAYER_LABEL[k.pace_layer] ?? k.pace_layer}층</Badge>
          <Badge variant="outline" className={cn("text-[10px]",
            contested ? "text-destructive border-destructive/50"
              : k.epistemic_status === "corroborated" ? "text-primary border-primary/40"
                : k.is_mine ? "text-hypothesis border-hypothesis/40" : "text-muted-foreground")}>
            {contested && <Swords className="h-2.5 w-2.5 mr-0.5" />}
            {EPISTEMIC_LABEL[k.epistemic_status] ?? k.epistemic_status}
          </Badge>
          {q && (
            <Badge variant="outline" className={cn("text-[10px] gap-1", q.cls)}
              title={`${q.hint} · 주목 ${k.salience} × 확신 ${k.conviction}`}>
              <QuadrantGlyph quadrant={k.quadrant} />{q.label}
            </Badge>
          )}
          {k.is_mine && <Badge variant="secondary" className="text-[9px]">내 지식</Badge>}
          <span className="ml-auto flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground tabular-nums">{k.created_at.slice(0, 10)}</span>
            {k.is_mine && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <button className="text-muted-foreground/60 hover:text-destructive" title="삭제">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>이 지식을 삭제할까요?</AlertDialogTitle>
                    <AlertDialogDescription className="text-left">
                      "{k.statement}"<br />내가 주입한 가설이라 삭제할 수 있습니다. 되돌릴 수 없습니다.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>취소</AlertDialogCancel>
                    <AlertDialogAction onClick={() => del.mutate()}>삭제</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </span>
        </div>

        <p className="text-sm leading-snug">{k.statement}</p>

        <div className="text-[11px] text-muted-foreground tabular-nums">
          독립 관측 {k.independent} · 지지 {k.support}
          {k.refute > 0 && <span className="text-destructive"> · 반박 {k.refute}</span>}
          {k.source_types > 1 && <span> · 소스 {k.source_types}종</span>}
        </div>

        {(k.rationale || k.source_ref) && (
          <div className="text-[11px] text-muted-foreground">
            {k.rationale && <div>근거: {k.rationale}</div>}
            {k.source_ref && <div>출처: {k.source_ref}</div>}
          </div>
        )}

        {k.entities.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {k.entities.map((e) => (
              <Link key={`${e.type}-${e.name}`}
                to={e.type === "company" && e.aliases ? `/analyze/${e.aliases}/summary`
                  : e.type === "person" ? `/person?name=${encodeURIComponent(e.name)}`
                    : `/feed?${e.type === "industry" || e.type === "sector" ? "industry" : "topic"}=${encodeURIComponent(e.name)}`}>
                <Badge variant="outline" className="text-[10px] font-normal hover:border-primary hover:text-primary">{e.name}</Badge>
              </Link>
            ))}
          </div>
        )}

        {k.falsifiers.length > 0 && (
          <div className="rounded-md border border-dashed px-2.5 py-1.5 space-y-0.5">
            <p className="text-[10px] font-medium text-muted-foreground">반증 조건 — 이 신호가 관측되면 이 지식은 흔들린다</p>
            {k.falsifiers.map((f, i) => (
              <div key={i} className="flex items-start gap-1.5 text-[11px]">
                <span className={cn("mt-1 h-1.5 w-1.5 rounded-full shrink-0",
                  f.triggered_at ? "bg-destructive" : "bg-muted-foreground/40")} />
                {f.triggered_at && f.triggered_doc_id ? (
                  <Link to={`/doc/${f.triggered_doc_id}`} className="text-destructive hover:underline">
                    {f.condition} — {f.triggered_at.slice(0, 10)} 감지됨 →
                  </Link>
                ) : (
                  <span className={f.triggered_at ? "text-destructive" : "text-muted-foreground"}>
                    {f.condition}{f.triggered_at && ` — ${f.triggered_at.slice(0, 10)} 감지됨`}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="group/ev flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/ev:rotate-180" />
            근거 사슬 {k.support + k.refute}건
          </CollapsibleTrigger>
          <CollapsibleContent>{open && <EvidenceList knowledgeId={k.id} />}</CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

function EvidenceList({ knowledgeId }: { knowledgeId: number }) {
  const { data, isLoading } = useQuery(
    apiQuery<EvidenceDoc[]>({
      key: ["spine", "knowledge", knowledgeId, "evidence"],
      url: `/api/spine/knowledge/items/${knowledgeId}/evidence`, staleTime: STALE.short,
    }),
  )
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
        <Loader2 className="h-3 w-3 animate-spin" /> 근거 불러오는 중…
      </div>
    )
  }
  return (
    <ul className="mt-1.5 divide-y rounded-md border px-3">
      {(data ?? []).map((ev, i) => (
        <li key={i} className="flex items-center gap-2 py-1.5">
          <Badge variant={ev.stance === "refute" ? "destructive" : "secondary"} className="text-[9px] shrink-0">
            {ev.stance === "refute" ? "반박" : ev.stance === "attention" ? "주목" : "지지"}
          </Badge>
          {!ev.independent && <Badge variant="outline" className="text-[9px] shrink-0 text-muted-foreground">릴레이</Badge>}
          {ev.source_type && <SourceBadge sourceType={ev.source_type} />}
          {ev.doc_id ? (
            <Link to={`/doc/${ev.doc_id}`} className="text-xs truncate hover:underline">
              {ev.title || `문서 #${ev.doc_id}`}
            </Link>
          ) : <span className="text-xs text-muted-foreground">(사용자 행위)</span>}
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground tabular-nums">{ev.observed_at.slice(0, 10)}</span>
        </li>
      ))}
    </ul>
  )
}

function KnowledgeSkeleton() {
  return (
    <PageContainer gap="sm">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-12 w-full rounded-xl" />
      <Skeleton className="h-16 w-full rounded-xl" />
      <Skeleton className="h-32 w-full rounded-xl" />
      <Skeleton className="h-32 w-full rounded-xl" />
    </PageContainer>
  )
}
