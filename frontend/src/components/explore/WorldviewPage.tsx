import { lazy, Suspense, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
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
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet"
import { Checkbox } from "@/components/ui/checkbox"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Badge } from "@/components/ui/badge"
import { ArrowRight } from "lucide-react"
import { cn } from "@/lib/utils"

// PoC 뷰 — three.js(3D)/force-graph 번들을 메인에서 분리 (토글 시에만 로드)
const ForceGraph3DView = lazy(() => import("@/components/explore/graph/ForceGraph3DView"))
const ObsidianGraphView = lazy(() => import("@/components/explore/graph/ObsidianGraphView"))

const VIEW_MODES = [
  { value: "structure", label: "구조" },
  { value: "force3d", label: "3D" },
  { value: "obsidian", label: "옵시디언" },
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
  const s = nodeSize(n)
  const layer = n.pace_layer ?? ""
  return (
    <div
      className={cn(
        "rounded-md border bg-card px-2 py-1 text-xs shadow-sm",
        layer === "regime" && "border-2 border-foreground/50 bg-[color-mix(in_srgb,var(--foreground)_6%,var(--card))] shadow-md",
        layer === "structure" && "border-foreground/30 shadow",
        layer === "event" && "opacity-80",
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
  const [searchParams, setSearchParams] = useSearchParams()
  const view = searchParams.get("view") ?? "structure"   // URL=상태 소스: structure|force3d|obsidian
  const setView = (v: string) => setSearchParams((p) => {
    const n = new URLSearchParams(p)
    if (v === "structure") n.delete("view"); else n.set("view", v)
    return n
  }, { replace: true })
  const [lenses, setLenses] = useState<string[]>([])
  const [showSmall, setShowSmall] = useState(false)
  const [backboneOnly, setBackboneOnly] = useState(true)   // 기본=줄기만 (잔가지 숨김)
  const [focusId, setFocusId] = useState<number | null>(null)   // 초점(로컬) 모드 중심 노드
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
      id: String(n.id), type: "graphNode", position: { x: n.x, y: n.y }, data: n as unknown as Record<string, unknown>,
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
  }, [visNodes, visEdges])

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(builtNodes)
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(builtEdges)
  useEffect(() => setRfNodes(builtNodes), [builtNodes, setRfNodes])
  useEffect(() => setRfEdges(builtEdges), [builtEdges, setRfEdges])

  if (isLoading) return <PageContainer gap="sm"><Skeleton className="h-[620px] w-full rounded-xl" /></PageContainer>
  if (isError) return <ErrorState message="세계관 그래프를 불러오지 못했습니다" />

  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline gap-2 flex-wrap">
        <h1 className="text-lg font-bold">세계관 뷰 — 인과 그래프</h1>
        <span className="text-[11px] text-muted-foreground">
          {view === "structure" ? "근본 원인 → 수혜 (좌→우)"
            : view === "force3d" ? "3D 포스 그래프 (회전·줌, PoC)"
            : "옵시디언式 2D 포스 (hover 이웃 강조, PoC)"}
        </span>
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
        <div style={{ height: "calc(100vh - 240px)", minHeight: 560 }} className="rounded-xl border overflow-hidden">
          {view === "structure" ? (
            <ReactFlow
              key={`${focusId ?? "all"}-${depth}-${backboneOnly}`}   // 초점/필터 변경 시 재마운트 → fitView 재실행
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, n) => focusNode(n.data as unknown as WNode)}
              onEdgeClick={(_, e) => { setSelectedEdge(e.data as unknown as WEdge); setSelectedNode(null) }}
              fitView
              fitViewOptions={{ maxZoom: 0.9 }}
              minZoom={0.15}
            >
              <Background />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
          ) : (
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
              {view === "force3d" ? (
                <ForceGraph3DView nodes={visNodes} edges={visEdges} onNodeSelect={focusNode} />
              ) : (
                <ObsidianGraphView nodes={visNodes} edges={visEdges} onNodeSelect={focusNode} />
              )}
            </Suspense>
          )}
        </div>
      )}

      <NodeDetailSheet node={selectedNode} allEdges={data?.edges ?? []} onClose={() => setSelectedNode(null)} />
      <EdgeDetailSheet edge={selectedEdge} onClose={() => setSelectedEdge(null)} />
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
        {e.corroborated_by >= 2 && <Badge variant="outline" className="text-[9px] text-primary border-primary/40">{e.corroborated_by}개 확인</Badge>}
        {e.contested && <Badge variant="destructive" className="text-[9px]">상충</Badge>}
      </div>
      {e.mechanism && <p className="text-xs text-muted-foreground leading-snug">{e.mechanism}</p>}
    </li>
  )
}

function NodeDetailSheet({ node, allEdges, onClose }: { node: WNode | null; allEdges: WEdge[]; onClose: () => void }) {
  const { data } = useQuery(
    apiQuery<NodeNarrative[]>({
      key: ["spine", "causal", "node", node?.id ?? 0, "narratives"],
      url: `/api/spine/causal/node/${node?.id}/narratives`,
      enabled: !!node,
    }),
  )
  const causes = node ? allEdges.filter((e) => e.to_id === node.id) : []      // 이 노드로 들어오는 (원인)
  const effects = node ? allEdges.filter((e) => e.from_id === node.id) : []   // 이 노드에서 나가는 (결과)

  return (
    <Sheet open={!!node} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{node?.name}</SheetTitle>
          <SheetDescription>
            {node && (NODE_LABEL[node.type] ?? node.type)} · 유입 {node?.in_degree} · 유출 {node?.out_degree}
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 space-y-4 text-sm">
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
      </SheetContent>
    </Sheet>
  )
}

function EdgeDetailSheet({ edge, onClose }: { edge: WEdge | null; onClose: () => void }) {
  return (
    <Sheet open={!!edge} onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{edge?.from} → {edge?.to}</SheetTitle>
          <SheetDescription>{edge?.rel === "BENEFITS_FROM" ? "수혜" : "인과"}</SheetDescription>
        </SheetHeader>
        <div className="px-4 space-y-2 text-sm">
          {edge?.mechanism && <p>{edge.mechanism}</p>}
          <div className="flex flex-wrap gap-1.5">
            {edge && edge.corroborated_by >= 2 && (
              <Badge variant="outline" className="text-[9px] font-normal text-primary border-primary/40">
                {edge.corroborated_by}개 내러티브 확인
              </Badge>
            )}
            {edge?.contested && <Badge variant="destructive" className="text-[9px] font-normal">상충</Badge>}
            {edge?.flywheel && (
              <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                자기강화 루프
              </Badge>
            )}
            {edge?.promoted_knowledge_id && (
              <Badge variant="secondary" className="text-[9px] font-normal">승격된 지식</Badge>
            )}
          </div>
          {edge?.feedback_note && (
            <p className="text-[11px] text-muted-foreground border-l-2 border-hypothesis/40 pl-2">
              피드백 나선 판정: {edge.feedback_note}
            </p>
          )}
          {edge?.confidence != null && (
            <div className="text-xs text-muted-foreground">신뢰도 {(edge.confidence * 100).toFixed(0)}%</div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
