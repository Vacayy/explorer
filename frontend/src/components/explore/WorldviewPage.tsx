import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { useTheme } from "next-themes"
import { useQuery } from "@tanstack/react-query"
import dagre from "dagre"
import {
  ReactFlow, Background, Controls, MiniMap, Handle, Position, MarkerType,
  useNodesState, useEdgesState,
  type Node, type Edge, type NodeProps,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { apiQuery, STALE } from "@/api/query"
import { PageContainer } from "@/components/shared/PageContainer"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { Checkbox } from "@/components/ui/checkbox"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Badge } from "@/components/ui/badge"
import { ArrowRight, X, Maximize2, Minimize2 } from "lucide-react"
import { formatKrw } from "@/utils/format"
import { cn } from "@/lib/utils"

// 옵시디언 뷰 — force-graph 번들을 메인에서 분리 (토글 시에만 로드)
const ObsidianGraphView = lazy(() => import("@/components/explore/graph/ObsidianGraphView"))

const VIEW_MODES = [
  { value: "structure", label: "흐름" },     // 좌→우 인과 흐름 (dagre 시간축)
  { value: "obsidian", label: "관계망" },    // force 관계망 (옵시디언式)
] as const

/**
 * /narrative/worldview — 세계관 뷰 (그래프 시각화 기획서, docs/specs/causal-worldview.md).
 * narrative_id 스코프 없는 전역 인과 그래프를 노드-링크로. 좌(근본원인)→우(수혜) dagre 배치 —
 * "인과는 시간에 종속된다" 원칙을 시각 언어로. LLM 호출 없음(순수 조회+union-find 클러스터).
 */
interface WNode {
  id: number; name: string; type: string
  in_degree: number; out_degree: number; cluster_id: number
  in_flywheel?: boolean
  pace_layer?: string | null   // event|flow|cycle|structure|regime — 노드 중력 (D-030)
}
interface WEdge {
  from: string; from_id: number; from_type: string | null
  to: string; to_id: number; to_type: string | null
  rel: string; mechanism: string | null; orientation: string | null
  reference_period: string | null; confidence: number | null
  corroborated_by: number; contested: boolean; promoted_knowledge_id: number | null
  feedback_note?: string | null   // both_temporal 해소 근거 (시점 다른 피드백 나선, D-029)
  geo_scope?: string | null       // 인과 주장의 장소 스코프 (통제어휘, D-034)
  flywheel?: boolean
}
interface Worldview { nodes: WNode[]; edges: WEdge[] }
interface NodeNarrative { id: number; topic: string; title: string | null }

const NODE_LABEL: Record<string, string> = {
  company: "기업", sector: "섹터", theme: "테마", person: "인물",
  macro: "매크로", policy: "정책", event: "사건",
}
const LENS_LABEL: Record<string, string> = {
  macro: "매크로", geopolitics: "지정학", industry: "산업", flow: "수급", tech: "기술", policy: "정책",
}
const LENSES = Object.keys(LENS_LABEL)
const NODE_W = 150
const NODE_H = 44
const MIN_CLUSTER = 3   // 이보다 작은 연결요소(고립된 2노드 조각)는 기본 숨김 — 노이즈 감소

// 노드 중력 (D-030) — 느린 층일수록 크고 무겁게. 크기는 dagre 레이아웃에도 반영.
const LAYER_SIZE: Record<string, { w: number; h: number }> = {
  regime: { w: 190, h: 56 }, structure: { w: 168, h: 50 },
  cycle: { w: NODE_W, h: NODE_H }, flow: { w: NODE_W, h: NODE_H },
  event: { w: 132, h: 40 },
}
const LAYER_KO: Record<string, string> = {
  regime: "체제", structure: "구조", cycle: "사이클", flow: "수급", event: "사건",
}
const nodeSize = (n: WNode) => LAYER_SIZE[n.pace_layer ?? ""] ?? { w: NODE_W, h: NODE_H }

function layoutGraph(nodes: WNode[], edges: WEdge[]): (WNode & { x: number; y: number })[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: "LR", nodesep: 12, ranksep: 40 })
  g.setDefaultEdgeLabel(() => ({}))
  nodes.forEach((n) => {
    const s = nodeSize(n)
    g.setNode(String(n.id), { width: s.w, height: s.h })
  })
  edges.forEach((e) => g.setEdge(String(e.from_id), String(e.to_id)))
  dagre.layout(g)
  return nodes.map((n) => {
    const pos = g.node(String(n.id))
    const s = nodeSize(n)
    return { ...n, x: pos.x - s.w / 2, y: pos.y - s.h / 2 }
  })
}

function GraphNode({ data }: NodeProps) {
  const n = data as unknown as WNode
  const focal = (data as { isFocal?: boolean }).isFocal
  const s = nodeSize(n)
  const layer = n.pace_layer ?? ""
  return (
    <div
      className={cn(
        "rounded-md border bg-card px-2 py-1 text-xs shadow-sm",
        layer === "regime" && "border-2 border-foreground/50 bg-[color-mix(in_srgb,var(--foreground)_6%,var(--card))] shadow-md",
        layer === "structure" && "border-foreground/30 shadow",
        layer === "event" && "opacity-80",
        focal && "ring-2 ring-primary ring-offset-1 ring-offset-background border-primary shadow-lg",
      )}
      style={{ width: s.w }}
    >
      <div className="text-[9px] text-muted-foreground">
        {NODE_LABEL[n.type] ?? n.type}
        {layer && (layer === "regime" || layer === "structure") && ` · ${LAYER_KO[layer]}`}
      </div>
      <div className={cn("truncate", layer === "regime" ? "font-bold text-sm" : "font-medium")}>{n.name}</div>
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  )
}
const nodeTypes = { graphNode: GraphNode }

export default function WorldviewPage() {
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === "dark"
  const [fullscreen, setFullscreen] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const view = searchParams.get("view") === "obsidian" ? "obsidian" : "structure"   // URL=상태 소스 (stale 값은 structure로)
  const setView = (v: string) => setSearchParams((p) => {
    const n = new URLSearchParams(p)
    if (v === "structure") n.delete("view"); else n.set("view", v)
    return n
  }, { replace: true })
  const [lenses, setLenses] = useState<string[]>([])
  const [showSmall, setShowSmall] = useState(false)
  const [backboneOnly, setBackboneOnly] = useState(true)   // 기본=줄기만 (잔가지 숨김)
  // ?focus=<id> 로 딥링크 진입 시 그 노드에 초점 (신호 탭 그래프 활동 → 세계관)
  const focusParam = searchParams.get("focus")
  const [focusId, setFocusId] = useState<number | null>(focusParam ? Number(focusParam) : null)
  const [depth, setDepth] = useState(2)                     // 초점 N홉
  const [selectedNode, setSelectedNode] = useState<WNode | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<WEdge | null>(null)
  // 백엔드는 현재 단일 category만 지원 — 2개 이상 선택 시 필터 없이(합집합) 보여줌
  const category = lenses.length === 1 ? lenses[0] : undefined

  const { data, isLoading, isError } = useQuery(
    apiQuery<Worldview>({
      key: ["spine", "causal", "worldview", category ?? "all"],
      url: `/api/spine/causal/worldview${category ? `?category=${encodeURIComponent(category)}` : ""}`,
      staleTime: STALE.short,
    }),
  )

  // 1단계: 작은 연결요소 숨김 → base. 그 위에 초점(로컬 N홉) 또는 백본(줄기) 필터.
  // 세 뷰(구조·3D·옵시디언)가 공유하는 visNodes/visEdges.
  const { visNodes, visEdges, hiddenCount } = useMemo(() => {
    if (!data) return { visNodes: [] as WNode[], visEdges: [] as WEdge[], hiddenCount: 0 }
    const clusterSize = new Map<number, number>()
    data.nodes.forEach((n) => clusterSize.set(n.cluster_id, (clusterSize.get(n.cluster_id) ?? 0) + 1))
    const baseN = data.nodes.filter((n) => showSmall || (clusterSize.get(n.cluster_id) ?? 0) >= MIN_CLUSTER)
    const baseIds = new Set(baseN.map((n) => n.id))
    const baseE = data.edges.filter((e) => baseIds.has(e.from_id) && baseIds.has(e.to_id))
    const smallHidden = data.nodes.length - baseN.length

    // 초점 모드: 중심 노드에서 depth홉 이웃(무향 BFS)만 — 잔가지 포함 전체 이웃 (로컬 그래프)
    if (focusId != null && baseIds.has(focusId)) {
      const adj = new Map<number, number[]>()
      baseE.forEach((e) => {
        ;(adj.get(e.from_id) ?? adj.set(e.from_id, []).get(e.from_id)!).push(e.to_id)
        ;(adj.get(e.to_id) ?? adj.set(e.to_id, []).get(e.to_id)!).push(e.from_id)
      })
      const keep = new Set<number>([focusId])
      let frontier = [focusId]
      for (let d = 0; d < depth; d++) {
        const next: number[] = []
        frontier.forEach((id) => (adj.get(id) ?? []).forEach((nb) => {
          if (!keep.has(nb)) { keep.add(nb); next.push(nb) }
        }))
        frontier = next
      }
      const fN = baseN.filter((n) => keep.has(n.id))
      const fE = baseE.filter((e) => keep.has(e.from_id) && keep.has(e.to_id))
      return { visNodes: fN, visEdges: fE, hiddenCount: smallHidden }
    }

    // 개요 모드: 백본(줄기)만 — 차수 2+ 또는 느린 층(체제·구조) 또는 플라이휠. 잔가지(차수 1) 제거.
    if (backboneOnly) {
      const bN = baseN.filter((n) =>
        (n.in_degree + n.out_degree) >= 2 || n.pace_layer === "regime"
        || n.pace_layer === "structure" || n.in_flywheel)
      const bIds = new Set(bN.map((n) => n.id))
      const bE = baseE.filter((e) => bIds.has(e.from_id) && bIds.has(e.to_id))
      return { visNodes: bN, visEdges: bE, hiddenCount: smallHidden }
    }

    return { visNodes: baseN, visEdges: baseE, hiddenCount: smallHidden }
  }, [data, showSmall, backboneOnly, focusId, depth])

  const focalNode = useMemo(
    () => (focusId != null ? data?.nodes.find((n) => n.id === focusId) ?? null : null),
    [data, focusId])

  // 노드 클릭 = 초점 재중심 + 상세 패널(초점 이동 시 같은 패널이 갱신되어 맥락을 따라간다).
  const focusNode = (n: WNode) => { setFocusId(n.id); setSelectedNode(n); setSelectedEdge(null) }

  // 2단계: 구조 뷰(React Flow) 전용 — dagre 좌→우 배치 변환
  const { nodes: builtNodes, edges: builtEdges } = useMemo(() => {
    if (visEdges.length === 0) return { nodes: [] as Node[], edges: [] as Edge[] }
    const positioned = layoutGraph(visNodes, visEdges)
    const rfNodes: Node[] = positioned.map((n) => ({
      id: String(n.id), type: "graphNode", position: { x: n.x, y: n.y },
      data: { ...n, isFocal: n.id === focusId } as unknown as Record<string, unknown>,
    }))
    const rfEdges: Edge[] = visEdges.map((e, i) => ({
      id: `e${i}`, source: String(e.from_id), target: String(e.to_id),
      type: "smoothstep",
      style: {
        strokeDasharray: e.rel === "BENEFITS_FROM" ? "4 3" : undefined,
        stroke: e.contested ? "var(--destructive)"
          : e.flywheel ? "var(--hypothesis)" : "var(--muted-foreground)",
        strokeWidth: e.flywheel || e.corroborated_by >= 2 ? 2.5 : 1,
        opacity: e.flywheel || e.contested || e.corroborated_by >= 2 ? 1 : 0.45,
      },
      animated: !!e.flywheel,
      markerEnd: { type: MarkerType.ArrowClosed },
      data: e as unknown as Record<string, unknown>,
    }))
    return { nodes: rfNodes, edges: rfEdges }
  }, [visNodes, visEdges, focusId])

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(builtNodes)
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(builtEdges)
  useEffect(() => setRfNodes(builtNodes), [builtNodes, setRfNodes])
  useEffect(() => setRfEdges(builtEdges), [builtEdges, setRfEdges])

  if (isLoading) return <PageContainer gap="sm"><Skeleton className="h-[620px] w-full rounded-xl" /></PageContainer>
  if (isError) return <ErrorState message="세계관 그래프를 불러오지 못했습니다" />

  return (
    <PageContainer gap="sm">
      {/* 전체화면이면 뷰 전체(메뉴+그래프)가 화면을 덮는다 — 상단 컨트롤도 함께 노출 */}
      <div className={cn("flex flex-col gap-2", fullscreen && "fixed inset-0 z-50 bg-background p-4")}>
      <div className="flex items-baseline gap-2 flex-wrap">
        <h1 className="text-lg font-bold">세계관 뷰 (인과 그래프)</h1>
        <ToggleGroup type="single" value={view} onValueChange={(v) => v && setView(v)}
          className="ml-auto gap-1">
          {VIEW_MODES.map((m) => (
            <ToggleGroupItem key={m.value} value={m.value}
              className="h-7 px-3 text-xs rounded-lg text-muted-foreground data-[state=on]:border data-[state=on]:border-primary data-[state=on]:text-primary data-[state=on]:bg-accent">
              {m.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <div className="flex items-center gap-3 flex-wrap text-xs">
        {LENSES.map((l) => (
          <label key={l} className="flex items-center gap-1.5 cursor-pointer">
            <Checkbox
              checked={lenses.includes(l)}
              onCheckedChange={(v) =>
                setLenses((prev) => (v ? [...prev, l] : prev.filter((x) => x !== l)))
              }
            />
            {LENS_LABEL[l]}
          </label>
        ))}
        <label className={cn("flex items-center gap-1.5 cursor-pointer ml-auto text-muted-foreground",
          focusId != null && "opacity-40 pointer-events-none")}>
          <Checkbox checked={backboneOnly} onCheckedChange={(v) => setBackboneOnly(!!v)} />
          줄기만
        </label>
        <label className={cn("flex items-center gap-1.5 cursor-pointer text-muted-foreground",
          focusId != null && "opacity-40 pointer-events-none")}>
          <Checkbox checked={showSmall} onCheckedChange={(v) => setShowSmall(!!v)} />
          작은 조각{hiddenCount > 0 && !showSmall ? ` (숨김 ${hiddenCount})` : ""}
        </label>
      </div>

      {focalNode && (
        <div className="flex items-center gap-2 text-xs flex-wrap rounded-lg border border-primary/30 bg-accent/40 px-3 py-1.5">
          <Badge className="text-[10px]">초점</Badge>
          <span className="font-medium">{focalNode.name}</span>
          <span className="text-muted-foreground">이웃 {visNodes.length - 1}개</span>
          <span className="ml-2 text-muted-foreground">깊이</span>
          <ToggleGroup type="single" value={String(depth)}
            onValueChange={(v) => v && setDepth(Number(v))} className="gap-0.5">
            {[1, 2, 3].map((d) => (
              <ToggleGroupItem key={d} value={String(d)}
                className="h-6 w-6 p-0 text-[11px] rounded data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
                {d}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <button onClick={() => setSelectedNode(focalNode)}
            className="ml-auto text-primary hover:underline">상세</button>
          <button onClick={() => setFocusId(null)}
            className="text-primary hover:underline">전체 보기 ✕</button>
        </div>
      )}

      {!data || data.edges.length === 0 ? (
        <EmptyState message="인과 그래프가 아직 비어 있습니다 — 내러티브가 재생성되며 쌓입니다." />
      ) : (
        <div
          style={fullscreen ? undefined : { height: "calc(100vh - 160px)", minHeight: 620 }}
          className={cn(
            "relative border overflow-hidden bg-background rounded-xl",
            fullscreen && "flex-1 min-h-0",
          )}
        >
          {view === "structure" ? (
            <ReactFlow
              key={`${focusId ?? "all"}-${depth}-${backboneOnly}-${fullscreen}`}   // 초점·필터·전체화면 변경 시 재마운트 → fitView
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={nodeTypes}
              colorMode={isDark ? "dark" : "light"}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, n) => focusNode(n.data as unknown as WNode)}
              onEdgeClick={(_, e) => { setSelectedEdge(e.data as unknown as WEdge); setSelectedNode(null) }}
              fitView
              fitViewOptions={{ maxZoom: 0.9 }}
              minZoom={0.08}
              maxZoom={4}
            >
              <Background />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
          ) : (
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
              <ObsidianGraphView nodes={visNodes} edges={visEdges} onNodeSelect={focusNode}
                isDark={isDark} focusId={focusId} />
            </Suspense>
          )}

          {/* 전체화면 토글 — 그래프 영역이 화면을 덮게 */}
          <button
            onClick={() => setFullscreen((f) => !f)}
            className="absolute top-3 left-3 z-10 rounded-lg border bg-card/85 p-1.5 text-muted-foreground shadow hover:text-foreground backdrop-blur"
            aria-label={fullscreen ? "전체화면 종료" : "전체화면"}
          >
            {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>

          {/* 상세 — blur 드로어 대신 그래프 영역 안에 뜨는 패널 */}
          {selectedNode && (
            <NodeGraphPanel node={selectedNode} allEdges={data?.edges ?? []}
              onClose={() => setSelectedNode(null)} />
          )}
          {selectedEdge && (
            <EdgeGraphPanel edge={selectedEdge} onClose={() => setSelectedEdge(null)} />
          )}
        </div>
      )}
      </div>
    </PageContainer>
  )
}

function EdgeContextRow({ e, dir }: { e: WEdge; dir: "in" | "out" }) {
  // dir=in: {상대} → 이 노드 (원인) / dir=out: 이 노드 → {상대} (결과)
  const other = dir === "in" ? e.from : e.to
  const otherType = dir === "in" ? e.from_type : e.to_type
  return (
    <li className="rounded-lg border px-2.5 py-1.5 space-y-1">
      <div className="flex items-center gap-1.5 flex-wrap text-sm">
        {dir === "in" && <><span className="font-medium">{other}</span><ArrowRight className="h-3 w-3 text-muted-foreground" /></>}
        <Badge variant="outline" className="text-[9px]">
          {e.rel === "BENEFITS_FROM" ? "수혜" : "인과"}
        </Badge>
        {dir === "out" && <><ArrowRight className="h-3 w-3 text-muted-foreground" /><span className="font-medium">{other}</span></>}
        {otherType && <span className="text-[9px] text-muted-foreground">{NODE_LABEL[otherType] ?? otherType}</span>}
        {e.reference_period && <span className="text-[9px] text-muted-foreground">· {e.reference_period}</span>}
        {e.geo_scope && <Badge variant="outline" className="text-[9px]">{e.geo_scope}</Badge>}
        {e.corroborated_by >= 2 && <Badge variant="outline" className="text-[9px] text-primary border-primary/40">{e.corroborated_by}개 확인</Badge>}
        {e.contested && <Badge variant="destructive" className="text-[9px]">상충</Badge>}
      </div>
      {e.mechanism && <p className="text-xs text-muted-foreground leading-snug">{e.mechanism}</p>}
    </li>
  )
}

/* 그래프 영역 안에 뜨는 상세 패널 셸 — 우측 상단 플로팅, 화면 blur/드로어 없음 */
function GraphPanel({ title, subtitle, onClose, children }: {
  title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode
}) {
  return (
    <div className="absolute top-3 right-3 z-10 flex max-h-[calc(100%-24px)] w-[340px] flex-col rounded-xl border bg-card shadow-xl">
      <div className="flex items-start gap-2 border-b px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{title}</div>
          {subtitle && <div className="text-[11px] text-muted-foreground">{subtitle}</div>}
        </div>
        <button onClick={onClose} className="shrink-0 text-muted-foreground hover:text-foreground" aria-label="닫기">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
    </div>
  )
}

interface BeneficiaryCandidate {
  stock_code: string; entity_id: number; name: string
  rs_short: number | null; rs_prev: number | null
  per: number | null; pbr: number | null; market_cap: number | null; pos_52w: number | null
  co_mentions: number; relevance: number | null
}

// 수혜 섹터/테마 → 종목 후보 (문서 공동언급 + RS·밸류 스크린, action_thesis Phase 1, D-035)
function BeneficiarySection({ sector }: { sector: string }) {
  const { data, isLoading } = useQuery(
    apiQuery<BeneficiaryCandidate[]>({
      key: ["spine", "beneficiary", sector],
      url: `/api/spine/beneficiary/screen?sector=${encodeURIComponent(sector)}&limit=10`,
      staleTime: STALE.medium,
    }),
  )
  if (isLoading) return <div className="text-xs text-muted-foreground">수혜 후보 탐색 중…</div>
  const items = data ?? []
  if (items.length === 0) return null
  return (
    <div>
      <div className="text-xs font-medium mb-1.5 text-muted-foreground">
        수혜 후보 종목 ({items.length}) <span className="font-normal">· 문서 공동언급 + RS·밸류</span>
      </div>
      <ul className="space-y-1.5">
        {items.map((c) => (
          <li key={c.stock_code} className="rounded-lg border px-2.5 py-1.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              <a href={`/analyze/${c.stock_code}/summary`} className="font-medium text-sm hover:underline">{c.name}</a>
              {c.rs_short != null && (
                <Badge variant="outline" className="text-[9px] text-primary border-primary/40">RS {c.rs_short}</Badge>
              )}
              {c.relevance != null && <span className="text-[9px] text-muted-foreground">관련도 {Math.round(c.relevance * 100)}%</span>}
              {c.pos_52w != null && <span className="text-[9px] text-muted-foreground">52주 {c.pos_52w}%</span>}
              {c.market_cap != null && <span className="text-[9px] text-muted-foreground ml-auto">{formatKrw(c.market_cap)}</span>}
            </div>
            <div className="flex gap-2 text-[10px] text-muted-foreground mt-0.5 tabular-nums">
              {c.per != null && <span>PER {c.per.toFixed(1)}배</span>}
              {c.pbr != null && <span>PBR {c.pbr.toFixed(2)}배</span>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function NodeGraphPanel({ node, allEdges, onClose }: { node: WNode; allEdges: WEdge[]; onClose: () => void }) {
  const { data } = useQuery(
    apiQuery<NodeNarrative[]>({
      key: ["spine", "causal", "node", node.id, "narratives"],
      url: `/api/spine/causal/node/${node.id}/narratives`,
    }),
  )
  const causes = allEdges.filter((e) => e.to_id === node.id)      // 이 노드로 들어오는 (원인)
  const effects = allEdges.filter((e) => e.from_id === node.id)   // 이 노드에서 나가는 (결과)
  // 보편 노드의 "언제·어디서" — 연결된 인과 주장들의 시점·지역 집합 (D-034)
  const incident = [...causes, ...effects]
  const periods = [...new Set(incident.map((e) => e.reference_period).filter(Boolean))]
  const geos = [...new Set(incident.map((e) => e.geo_scope).filter(Boolean))]

  return (
    <GraphPanel
      title={node.name}
      subtitle={`${NODE_LABEL[node.type] ?? node.type} · 유입 ${node.in_degree} · 유출 ${node.out_degree}`}
      onClose={onClose}
    >
      <div className="space-y-4 text-sm">
        {(periods.length > 0 || geos.length > 0) && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground border-b pb-2">
            {periods.length > 0 && <span>관측 시점: {periods.join(" · ")}</span>}
            {geos.length > 0 && <span>지역: {geos.join(" · ")}</span>}
          </div>
        )}
        {(node.type === "sector" || node.type === "theme") && <BeneficiarySection sector={node.name} />}
        {causes.length > 0 && (
          <div>
            <div className="text-xs font-medium mb-1.5 text-muted-foreground">이 노드를 부르는 원인 ({causes.length})</div>
            <ul className="space-y-1.5">{causes.map((e, i) => <EdgeContextRow key={`c${i}`} e={e} dir="in" />)}</ul>
          </div>
        )}
        {effects.length > 0 && (
          <div>
            <div className="text-xs font-medium mb-1.5 text-muted-foreground">이 노드가 부르는 결과 ({effects.length})</div>
            <ul className="space-y-1.5">{effects.map((e, i) => <EdgeContextRow key={`e${i}`} e={e} dir="out" />)}</ul>
          </div>
        )}
        {causes.length === 0 && effects.length === 0 && (
          <div className="text-xs text-muted-foreground">연결된 인과가 아직 없습니다.</div>
        )}
        <div>
          <div className="text-xs font-medium mb-1 text-muted-foreground">등장하는 내러티브</div>
          {(data ?? []).length === 0 ? (
            <div className="text-xs text-muted-foreground">없음</div>
          ) : (
            <ul className="space-y-1">
              {(data ?? []).map((n) => (
                <li key={n.id}>
                  <a href={`/narrative?topic=${encodeURIComponent(n.topic)}`} className="text-xs hover:underline">
                    <Badge variant="secondary" className="text-[10px] mr-1">{n.topic}</Badge>
                    {n.title}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </GraphPanel>
  )
}

function EdgeGraphPanel({ edge, onClose }: { edge: WEdge; onClose: () => void }) {
  return (
    <GraphPanel
      title={`${edge.from} → ${edge.to}`}
      subtitle={edge.rel === "BENEFITS_FROM" ? "수혜" : "인과"}
      onClose={onClose}
    >
      <div className="space-y-2 text-sm">
        {(edge.reference_period || edge.geo_scope) && (
          <div className="flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
            {edge.reference_period && <span>시점: {edge.reference_period}</span>}
            {edge.geo_scope && <span>· 지역: {edge.geo_scope}</span>}
          </div>
        )}
        {edge.mechanism && <p>{edge.mechanism}</p>}
        <div className="flex flex-wrap gap-1.5">
          {edge.corroborated_by >= 2 && (
            <Badge variant="outline" className="text-[9px] font-normal text-primary border-primary/40">
              {edge.corroborated_by}개 내러티브 확인
            </Badge>
          )}
          {edge.contested && <Badge variant="destructive" className="text-[9px] font-normal">상충</Badge>}
          {edge.flywheel && (
            <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
              자기강화 루프
            </Badge>
          )}
          {edge.promoted_knowledge_id && (
            <Badge variant="secondary" className="text-[9px] font-normal">승격된 지식</Badge>
          )}
        </div>
        {edge.feedback_note && (
          <p className="text-[11px] text-muted-foreground border-l-2 border-hypothesis/40 pl-2">
            피드백 나선 판정: {edge.feedback_note}
          </p>
        )}
        {edge.confidence != null && (
          <div className="text-xs text-muted-foreground">신뢰도 {(edge.confidence * 100).toFixed(0)}%</div>
        )}
      </div>
    </GraphPanel>
  )
}
