import { useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Anchor, ArrowLeft, ArrowRight, ChevronDown, GitMerge, Loader2, Route, Sparkles, Workflow } from "lucide-react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { EmptyState } from "@/components/shared/ErrorState"
import { Markdown } from "@/components/shared/Markdown"
import { PageContainer } from "@/components/shared/PageContainer"
import { NarrativeList } from "@/components/explore/NarrativeList"
import { BeneficiaryList, ScenarioBeneficiaries, type ScenarioBeneficiary } from "@/components/explore/graph/CausalDetail"
import { cn } from "@/lib/utils"

/**
 * /narrative?topic= — 주제 내러티브 (theme_surge 고도화, D-023 인과 그래프 위 서브그래프).
 * 질문형 제목 + 서사(md) + 인과 체인 구조 뷰(그래프에서 조회) + category/version.
 * 도시에 2단 패턴: GET 캐시 → stale이면 compute 자동 발화.
 */
interface Narrative {
  status: string
  title: string | null
  narrative: string | null
  created_at: string | null
  stale: boolean
  category: string | null
  version: number | null
  narrative_id: number | null
}

const LENS_LABEL: Record<string, string> = {
  macro: "매크로", geopolitics: "지정학", industry: "산업", flow: "수급", tech: "기술", policy: "정책",
}

export default function NarrativePage() {
  const [sp] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const topic = sp.get("topic") ?? ""

  const cached = useQuery(
    apiQuery<Narrative>({
      key: ["spine", "narrative", topic],
      url: `/api/spine/narrative?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short, enabled: !!topic,
    }),
  )
  const fresh = useQuery(
    apiComputeQuery<Narrative>({
      key: ["spine", "narrative", topic, "compute"],
      url: `/api/spine/narrative/compute?topic=${encodeURIComponent(topic)}`,
      enabled: !!cached.data?.stale,
    }),
  )
  // 재생성 완료 시 캐시 GET을 무효화 → 새 version·category·narrative_id·인과 그래프 반영
  useEffect(() => {
    if (fresh.data?.status === "fresh") {
      qc.invalidateQueries({ queryKey: ["spine", "narrative", topic] })
    }
  }, [fresh.data?.status, topic, qc])
  const n = fresh.data ?? cached.data

  // topic 없이 진입 = 월드모델>내러티브 탭 랜딩 → 내러티브 목록
  if (!topic) return <NarrativeLanding />
  if (cached.isLoading) return <PageContainer gap="sm"><Skeleton className="h-8 w-96" /><Skeleton className="h-64 w-full rounded-xl" /></PageContainer>

  const generating = fresh.isFetching
  const empty = n?.status === "empty" && !n?.narrative && !generating
  const lenses = (cached.data?.category ?? n?.category ?? "").split(",").filter(Boolean)
  const version = cached.data?.version
  const narrativeId = cached.data?.narrative_id

  return (
    <PageContainer gap="sm" width="reading">
      <div className="flex items-center gap-2 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate("/narrative")}>
          <ArrowLeft className="h-4 w-4" /> 내러티브
        </Button>
        <Badge variant="secondary" className="text-[10px]">내러티브</Badge>
        {lenses.map((l) => (
          <Badge key={l} variant="outline" className="text-[10px]">{LENS_LABEL[l] ?? l}</Badge>
        ))}
        {version && version > 1 && (
          <Badge variant="outline" className="text-[10px] text-muted-foreground">v{version}</Badge>
        )}
      </div>

      {narrativeId && version && version > 1 && <DriftBadge narrativeId={narrativeId} />}

      {empty ? (
        <EmptyState message={`'${topic}' 관련 문서가 아직 충분하지 않습니다 (3건 이상 필요).`} />
      ) : (
        <>
          <h1 className="text-xl font-bold leading-snug flex items-start gap-2">
            <Sparkles className="h-5 w-5 text-hypothesis shrink-0 mt-0.5" />
            {n?.title ?? topic}
          </h1>
          {generating && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              최근 문서를 엮어 내러티브 생성 중… (수십 초)
            </div>
          )}
          {n?.narrative && (
            <Tabs defaultValue="narrative">
              <TabsList>
                <TabsTrigger value="narrative">서사</TabsTrigger>
                <TabsTrigger value="mer">인과 흐름 (메르 모드)</TabsTrigger>
              </TabsList>
              <TabsContent value="narrative">
                <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_6%,var(--card))]">
                  <CardContent className="py-4">
                    <Markdown>{n.narrative}</Markdown>
                    <div className="text-right mt-2">
                      <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                        AI 내러티브 · 문서 집합 변경 시 갱신 — 검증 필요
                        {n.created_at && ` · ${n.created_at.slice(0, 10)}`}
                      </Badge>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>
              <TabsContent value="mer">
                <MerNarrativeCard topic={topic} />
              </TabsContent>
            </Tabs>
          )}
          <ScenarioSection topic={topic} />
          {narrativeId && <CausalChain narrativeId={narrativeId} />}
          {narrativeId && <ChainPaths narrativeId={narrativeId} />}
          <Card><CardContent className="py-3">
            <div className="flex items-center gap-1.5 mb-2">
              <Sparkles className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">언급 상위 종목</span>
              <span className="text-[11px] text-muted-foreground">참고 · 이 테마와 자주 함께 언급 (공동언급) · RS·밸류</span>
            </div>
            <BeneficiaryList sector={topic} />
          </CardContent></Card>
          {narrativeId && <Grounding narrativeId={narrativeId} />}
          {narrativeId && <RelatedNarratives narrativeId={narrativeId} />}
        </>
      )}
    </PageContainer>
  )
}

/* ---------- 랜딩 (월드모델>내러티브 탭 — topic 없이 진입) ---------- */

function NarrativeLanding() {
  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xl font-bold">내러티브</h2>
        <span className="text-[11px] text-muted-foreground">주목받는 주제들을 관통하는 시장의 질문</span>
      </div>
      <MegaNarrativeSection />
      <NarrativeList empty="state" controls />
    </PageContainer>
  )
}

/* ---------- 메가 내러티브 — 공유노드 군집의 상위 세계관 서사 (D-031) ---------- */

interface MegaNarrative {
  id: number
  name: string
  title: string | null
  narrative: string | null
  members: string[]
  version: number
  created_at: string | null
}

function MegaNarrativeSection() {
  const navigate = useNavigate()
  const [openId, setOpenId] = useState<number | null>(null)
  const { data } = useQuery(
    apiQuery<MegaNarrative[]>({
      key: ["spine", "narrative", "mega"],
      url: "/api/spine/narrative/mega",
      staleTime: STALE.medium,
    }),
  )
  const items = data ?? []
  if (items.length === 0) return null

  return (
    <div className="space-y-2.5">
      {items.map((m) => (
        <Card key={m.id} className="bg-[color-mix(in_srgb,var(--primary)_5%,var(--card))]">
          <CardContent className="py-3 space-y-2">
            <Collapsible open={openId === m.id} onOpenChange={(o) => setOpenId(o ? m.id : null)}>
              <CollapsibleTrigger asChild>
                <button className="w-full text-left group">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge className="text-[10px]">세계관</Badge>
                    <span className="font-semibold text-sm group-hover:underline">{m.title ?? m.name}</span>
                    {m.version > 1 && (
                      <Badge variant="outline" className="text-[10px] text-muted-foreground">v{m.version}</Badge>
                    )}
                    <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground ml-auto transition-transform shrink-0",
                      openId === m.id && "rotate-180")} />
                  </div>
                  <div className="flex items-center gap-1 flex-wrap mt-1.5">
                    <span className="text-[10px] text-muted-foreground mr-0.5">{m.members.length}개 서사를 관통 —</span>
                    {m.members.map((t) => (
                      <Badge key={t} variant="secondary" className="text-[10px] cursor-pointer hover:bg-accent"
                        onClick={(e) => { e.stopPropagation(); navigate(`/narrative?topic=${encodeURIComponent(t)}`) }}>
                        {t}
                      </Badge>
                    ))}
                  </div>
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                {m.narrative && (
                  <div className="pt-2">
                    <Markdown>{m.narrative}</Markdown>
                    <div className="text-right mt-2">
                      <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                        AI 세계관 서사 · 부분 서사 변경 시 갱신 — 검증 필요
                        {m.created_at && ` · ${m.created_at.slice(0, 10)}`}
                      </Badge>
                    </div>
                  </div>
                )}
              </CollapsibleContent>
            </Collapsible>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

/* ---------- 파급 시나리오 (scenario 엔진 연결 — '왜·그래서 무엇', 온디맨드 opus) ---------- */

interface ScenarioResult {
  status: string
  answer: string | null
  beneficiaries: ScenarioBeneficiary[]
  citations: { n: number; doc_id: number; title: string; url: string }[]
}

function ScenarioSection({ topic }: { topic: string }) {
  const [run, setRun] = useState(false)
  const { data, isFetching } = useQuery(
    apiComputeQuery<ScenarioResult>({
      key: ["spine", "narrative", "scenario", topic],
      url: `/api/spine/narrative/scenario/compute?topic=${encodeURIComponent(topic)}`,
      enabled: run,
    }),
  )
  const loading = run && (isFetching || !data)
  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <Route className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">파급 시나리오</span>
          <span className="text-[11px] text-muted-foreground">사건을 1·2·3차 인과 체인으로 — 왜, 그래서 무엇</span>
          {!run && (
            <Button size="sm" className="ml-auto h-7" onClick={() => setRun(true)}>
              <Sparkles className="h-3.5 w-3.5" /> 파급 분석
            </Button>
          )}
        </div>
        {loading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            파급 체인을 전개하는 중… (수십 초~수 분, 심층 추론)
          </div>
        )}
        {run && data && data.status !== "ok" && (
          <EmptyState message="파급 분석을 생성하지 못했습니다 — 잠시 후 다시 시도." />
        )}
        {run && data?.status === "ok" && data.answer && (
          <Card className="bg-[color-mix(in_srgb,var(--primary)_5%,var(--card))]">
            <CardContent className="py-4 space-y-3">
              <Markdown>{data.answer}</Markdown>
              {data.beneficiaries?.length > 0 && (
                <div className="border-t pt-3">
                  <ScenarioBeneficiaries items={data.beneficiaries} event={topic} />
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 인과 체인 구조 뷰 (그래프에서 조회) ---------- */

interface CausalEdge {
  from: string; from_type: string | null; to: string; to_type: string | null
  rel: string; mechanism: string | null; orientation: string | null
  reference_period: string | null; confidence: number | null
  corroborated_by?: number; contested?: boolean; promoted_knowledge_id?: number | null
}
interface CausalGraph { nodes: { name: string; type: string }[]; edges: CausalEdge[] }

const NODE_LABEL: Record<string, string> = {
  company: "기업", sector: "섹터", theme: "테마", person: "인물",
  macro: "매크로", policy: "정책", event: "사건",
}
const ORIENT: Record<string, { label: string; cls: string }> = {
  past: { label: "회고", cls: "text-muted-foreground" },
  current: { label: "현재", cls: "text-foreground" },
  forward: { label: "전망", cls: "text-hypothesis" },
}
const ORIENT_ORDER: Record<string, number> = { past: 0, current: 1, forward: 2 }

function NodeChip({ name, type }: { name: string; type: string | null }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs">
      {type && <span className="text-[9px] text-muted-foreground">{NODE_LABEL[type] ?? type}</span>}
      <span className="font-medium">{name}</span>
    </span>
  )
}

function CausalChain({ narrativeId }: { narrativeId: number }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<CausalGraph>({
      key: ["spine", "narrative", "causal", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/causal`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-24 w-full rounded-xl" />
  if (isError) return null   // 본문은 이미 노출됨 — 구조 뷰만 조용히 생략

  const edges = [...(data?.edges ?? [])].sort(
    (a, b) => (ORIENT_ORDER[a.orientation ?? ""] ?? 1) - (ORIENT_ORDER[b.orientation ?? ""] ?? 1),
  )

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5">
          <Workflow className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">인과 구조</span>
          <span className="text-[11px] text-muted-foreground">시간순 · 원인 → 결과, 수혜 섹터</span>
        </div>
        {edges.length === 0 ? (
          <EmptyState message="인과 구조가 아직 추출되지 않았습니다 — 재생성 시 그래프에 쌓입니다." />
        ) : (
          <ul className="space-y-1.5">
            {edges.map((e, i) => {
              const o = ORIENT[e.orientation ?? ""]
              const benefit = e.rel === "BENEFITS_FROM"
              return (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-sm">
                  <NodeChip name={e.from} type={e.from_type} />
                  <span className={cn("inline-flex items-center gap-0.5 text-[10px]",
                    benefit ? "text-primary" : "text-muted-foreground")}>
                    <ArrowRight className="h-3 w-3" />
                    {benefit ? "수혜" : "인과"}
                    {o && <span className={cn("ml-0.5", o.cls)}>· {o.label}</span>}
                  </span>
                  <NodeChip name={e.to} type={e.to_type} />
                  {(e.corroborated_by ?? 0) >= 2 && (
                    <Badge variant="outline" className="text-[9px] font-normal text-primary border-primary/40">
                      {e.corroborated_by}개 내러티브 확인
                    </Badge>
                  )}
                  {e.contested && (
                    <Badge variant="destructive" className="text-[9px] font-normal">상충</Badge>
                  )}
                  {e.promoted_knowledge_id && (
                    <Badge variant="secondary" className="text-[9px] font-normal">승격된 지식</Badge>
                  )}
                  {e.mechanism && (
                    <span className="text-[11px] text-muted-foreground w-full pl-1">↳ {e.mechanism}</span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 버전 드리프트 (직전 버전 대비 인과 변화, Phase 2 §2-3) ---------- */

interface VersionDiff {
  status: string
  added_nodes: string[]
  removed_nodes: string[]
  added_edges: CausalEdge[]
  removed_edges: CausalEdge[]
  summary: string | null
}

function DriftBadge({ narrativeId }: { narrativeId: number }) {
  const [open, setOpen] = useState(false)
  const { data } = useQuery(
    apiQuery<VersionDiff>({
      key: ["spine", "narrative", "diff", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/diff`,
      staleTime: STALE.short,
    }),
  )
  if (!data || data.status !== "ok" || (data.added_edges.length === 0 && data.removed_edges.length === 0)) {
    return null
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className="inline-flex items-center gap-1 rounded-md border border-primary/40 px-2 py-0.5 text-[11px] text-primary">
          지난 버전 대비 달라진 것
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <Card className="mt-1.5">
          <CardContent className="py-2.5 space-y-1.5 text-xs">
            {data.summary && <p>{data.summary}</p>}
            {data.added_edges.length > 0 && (
              <div className="text-primary">
                + {data.added_edges.map((e) => `${e.from}→${e.to}`).join(" · ")}
              </div>
            )}
            {data.removed_edges.length > 0 && (
              <div className="text-muted-foreground line-through decoration-muted-foreground/50">
                {data.removed_edges.map((e) => `${e.from}→${e.to}`).join(" · ")}
              </div>
            )}
          </CardContent>
        </Card>
      </CollapsibleContent>
    </Collapsible>
  )
}

/* ---------- 메르 모드 (순회 top-1 경로 정박 서사, Phase 2 §2-2) ---------- */

interface MerNarrativeResponse {
  status: string
  narrative: string | null
  path: { nodes: { name: string; type: string }[] } | null
  stale: boolean
}

function MerNarrativeCard({ topic }: { topic: string }) {
  const qc = useQueryClient()
  const cachedMer = useQuery(
    apiQuery<MerNarrativeResponse>({
      key: ["spine", "narrative", "mer", topic],
      url: `/api/spine/narrative/mer?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short,
    }),
  )
  const freshMer = useQuery(
    apiComputeQuery<MerNarrativeResponse>({
      key: ["spine", "narrative", "mer", topic, "compute"],
      url: `/api/spine/narrative/mer/compute?topic=${encodeURIComponent(topic)}`,
      enabled: !!cachedMer.data?.stale,
    }),
  )
  useEffect(() => {
    if (freshMer.data?.status === "fresh") {
      qc.invalidateQueries({ queryKey: ["spine", "narrative", "mer", topic] })
    }
  }, [freshMer.data?.status, topic, qc])
  const m = freshMer.data ?? cachedMer.data
  const generating = freshMer.isFetching

  if (cachedMer.isLoading) return <Skeleton className="h-40 w-full rounded-xl" />
  if (!m || !m.narrative) {
    return <EmptyState message="아직 순회 가능한 인과 경로가 없습니다 — 인과가 더 쌓이면 나타납니다." />
  }

  return (
    <div className="space-y-2">
      {generating && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          인과 체인을 서사로 엮는 중…
        </div>
      )}
      <Card className="bg-[color-mix(in_srgb,var(--primary)_6%,var(--card))]">
        <CardContent className="py-4 space-y-3">
          <p className="text-sm leading-relaxed">{m.narrative}</p>
          {m.path && (
            <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t">
              {m.path.nodes.map((nd, j) => (
                <span key={j} className="flex items-center gap-1.5">
                  <span className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs">
                    <span className="text-[9px] text-muted-foreground">{NODE_LABEL[nd.type] ?? nd.type}</span>
                    <span className="font-medium">{nd.name}</span>
                  </span>
                  {j < m.path!.nodes.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ---------- 근본 원인 → 수혜 경로 (전역 그래프 순회, Phase 2 §2-1) ---------- */

interface ChainPath {
  nodes: { name: string; type: string }[]
  edges: CausalEdge[]
  confidence: number
  reaches_sector: boolean
}
interface ChainResponse { status: string; paths: ChainPath[] }

function ChainPaths({ narrativeId }: { narrativeId: number }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<ChainResponse>({
      key: ["spine", "narrative", "chain", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/chain`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-20 w-full rounded-xl" />
  // 엣지 부족(순회 불가)이거나 실패 — 섹션 자체를 조용히 숨김 (5-state: Empty/Error)
  if (isError || !data || data.status !== "ok" || data.paths.length === 0) return null

  return (
    <Card>
      <CardContent className="py-3 space-y-2.5">
        <div className="flex items-center gap-1.5">
          <Route className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">근본 원인 → 수혜 경로</span>
          <span className="text-[11px] text-muted-foreground">전역 인과 그래프 순회</span>
        </div>
        <ul className="space-y-2.5">
          {data.paths.map((p, i) => (
            <li key={i} className="flex flex-wrap items-center gap-1.5 text-sm">
              {p.nodes.map((n, j) => {
                const isRoot = j === 0
                const isBeneficiary = j === p.nodes.length - 1 && p.reaches_sector
                return (
                  <span key={j} className="flex items-center gap-1.5">
                    <span className={cn(
                      "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs",
                      isRoot && "border-hypothesis/50 bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]",
                      isBeneficiary && "border-primary/50 bg-[color-mix(in_srgb,var(--primary)_8%,var(--card))]",
                    )}>
                      <span className="text-[9px] text-muted-foreground">{NODE_LABEL[n.type] ?? n.type}</span>
                      <span className="font-medium">{n.name}</span>
                    </span>
                    {j < p.nodes.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                  </span>
                )
              })}
              <Badge variant="outline" className="text-[9px] font-normal text-muted-foreground ml-1">
                신뢰도 {(p.confidence * 100).toFixed(0)}%
              </Badge>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

/* ---------- 딛고 선 지식 (내러티브↔지식 루프, Phase 2 §2-5) ---------- */

interface GroundingItem {
  knowledge_id: number; statement: string; epistemic_status: string; falsifiers: string[]
}
interface GroundingResponse { status: string; grounding: GroundingItem[] }

function Grounding({ narrativeId }: { narrativeId: number }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<GroundingResponse>({
      key: ["spine", "narrative", "grounding", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/grounding`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-16 w-full rounded-xl" />
  if (isError || !data || data.status !== "ok" || data.grounding.length === 0) return null

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5">
          <Anchor className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">이 서사가 딛고 선 지식</span>
          <span className="text-[11px] text-muted-foreground">{data.grounding.length}건</span>
        </div>
        <ul className="space-y-2">
          {data.grounding.map((g) => (
            <li key={g.knowledge_id} className="text-sm space-y-0.5">
              <p>{g.statement}</p>
              {g.falsifiers.length > 0 && (
                <div className="text-[11px] text-muted-foreground">
                  흔들릴 조건: {g.falsifiers.join(" · ")}
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

/* ---------- 공유 내러티브 (같은 그래프의 다른 서브그래프, Phase 2 §2-4 머지) ---------- */

interface RelatedNarrative {
  narrative_id: number; topic: string; title: string | null; shared_nodes: string[]
}
interface RelatedResponse { status: string; related: RelatedNarrative[] }

function RelatedNarratives({ narrativeId }: { narrativeId: number }) {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useQuery(
    apiQuery<RelatedResponse>({
      key: ["spine", "narrative", "related", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/related`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-16 w-full rounded-xl" />
  if (isError || !data || data.status !== "ok" || data.related.length === 0) return null

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5">
          <GitMerge className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">이 인과를 공유하는 다른 내러티브</span>
          <span className="text-[11px] text-muted-foreground">{data.related.length}개</span>
        </div>
        <ul className="space-y-1.5">
          {data.related.map((r) => (
            <li key={r.narrative_id}>
              <button
                onClick={() => navigate(`/narrative?topic=${encodeURIComponent(r.topic)}`)}
                className="flex flex-wrap items-center gap-1.5 text-left text-sm hover:underline"
              >
                <Badge variant="secondary" className="text-[10px]">{r.topic}</Badge>
                <span className="text-muted-foreground text-xs truncate">{r.title}</span>
              </button>
              <div className="pl-1 text-[11px] text-muted-foreground">
                공유 노드: {r.shared_nodes.join(" · ")}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
