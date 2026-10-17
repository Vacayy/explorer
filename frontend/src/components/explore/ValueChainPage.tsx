import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useTheme } from "next-themes"
import dagre from "dagre"
import { ReactFlow, Background, Controls, Handle, Position, MarkerType, type Edge, type Node, type NodeProps } from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageHeader, PageLayout } from "@/components/shared/PageLayout"
import { SparkLine } from "@/components/shared/Spark"
import { KrConfirmStrip } from "@/components/shared/TwLinkSignal"
import { useKrConfirm, usePropagation, useValueChain } from "@/hooks/useTwRevenue"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { PropRow, VcEdge, VcNode } from "@/types"

/**
 * 탐색 › 밸류체인 (docs/specs/value-chain.md §5) — 최종 수요 ← 대만 공급 단계 ← 한국 종목.
 * 위: 번지는 중(한국 확인 전·엇갈림·선행 경보). 가운데: 지도(노드 = 이번 달 상태, 엣지 = 측정 판정·시차). 아래: 한국 확인 신호 전체.
 * 선택한 노드는 URL node. 예측력은 '대만은 매달, 한국은 분기'라는 공시 시차에서 나온다(D-251).
 */

const NODE_W = 188
const NODE_H = 66
const STATE_CLS: Record<string, string> = {
  "가속": "border-up/60 bg-up/5", "전환↑": "border-up/60 bg-up/5",
  "둔화": "border-down/60 bg-down/5", "전환↓": "border-down/60 bg-down/5", "유지": "border-border",
}
const DIR: Record<string, string> = { up: "↑", down: "↓", flat: "→" }
const lagText = (lag: number | null | undefined) => lag == null ? "" : lag === 0 ? "동행" : lag > 0 ? `공급 ${lag}개월 앞섬` : `수요 ${-lag}개월 앞섬`

type ChainNodeData = { node?: VcNode; demand?: { name: string; description: string }; selected: boolean }

function ChainNode({ data }: NodeProps) {
  const d = data as unknown as ChainNodeData
  if (d.demand) return <div className="w-[188px] rounded-md border-2 border-dashed px-2 py-1.5 text-xs">
    <Handle type="target" position={Position.Left} className="!opacity-0" />
    <div className="font-semibold">{d.demand.name}</div>
    <div className="truncate text-[10px] text-muted-foreground">{d.demand.description}</div>
  </div>
  const n = d.node!
  const krOnly = !n.tw.length
  return <div className={cn("w-[188px] rounded-md border bg-card px-2 py-1.5 text-xs shadow-sm", n.state ? STATE_CLS[n.state] : "", krOnly && "border-dashed",
    d.selected && "ring-2 ring-primary ring-offset-1 ring-offset-background")}>
    <Handle type="target" position={Position.Left} className="!opacity-0" />
    <Handle type="source" position={Position.Right} className="!opacity-0" />
    <div className="flex items-center gap-1">
      <span className="truncate font-semibold">{n.name}</span>
      {n.state && <span className={cn("ml-auto shrink-0 text-[10px]", n.state.startsWith("가속") || n.state === "전환↑" ? "text-up" : n.state === "유지" ? "text-muted-foreground" : "text-down")}>{n.state}</span>}
    </div>
    <div className="text-[10px] tabular-nums text-muted-foreground">
      {krOnly ? "대만 관측 없음 — 한국 원천으로" : `3M YoY ${formatPercent(n.yoy_3m)}`}
    </div>
    {n.kr.length > 0 && <div className="truncate text-[10px] font-medium text-primary">한국 {n.kr.map(k => k.name).join("·")}</div>}
  </div>
}
const nodeTypes = { chain: ChainNode }

function layout(nodes: string[], edges: [string, string][]) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: "LR", nodesep: 10, ranksep: 90 })
  g.setDefaultEdgeLabel(() => ({}))
  nodes.forEach(k => g.setNode(k, { width: NODE_W, height: NODE_H }))
  edges.forEach(([a, b]) => g.setEdge(a, b))
  dagre.layout(g)
  return Object.fromEntries(nodes.map(k => { const p = g.node(k); return [k, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 }] }))
}

const EDGE_STYLE: Record<VcEdge["verdict"], { stroke: string; width: number; dash?: string; opacity: number }> = {
  "확인": { stroke: "var(--foreground)", width: 2.2, opacity: 0.85 },
  "부분": { stroke: "var(--foreground)", width: 1.4, opacity: 0.6 },
  "미확인": { stroke: "var(--muted-foreground)", width: 1, dash: "4 4", opacity: 0.45 },
  "관측 불가": { stroke: "var(--muted-foreground)", width: 1, dash: "1 4", opacity: 0.4 },
}

export default function ValueChainPage() {
  const vc = useValueChain()
  const prop = usePropagation()
  const confirms = useKrConfirm()
  const [params, setParams] = useSearchParams()
  const { resolvedTheme } = useTheme()
  const selected = params.get("node")
  const select = (k: string | null) => setParams(prev => { const n = new URLSearchParams(prev); if (k) n.set("node", k); else n.delete("node"); return n }, { replace: true, preventScrollReset: true })

  const graph = useMemo(() => {
    if (!vc.data) return { nodes: [] as Node[], edges: [] as Edge[] }
    const keys = [...vc.data.nodes.map(n => n.key), ...vc.data.demands.map(d => d.key)]
    const pos = layout(keys, vc.data.edges.map(e => [e.from, e.to]))
    const nodes: Node[] = [
      ...vc.data.nodes.map(n => ({ id: n.key, type: "chain", position: pos[n.key], data: { node: n, selected: n.key === selected } })),
      ...vc.data.demands.map(d => ({ id: d.key, type: "chain", position: pos[d.key], data: { demand: d, selected: false } })),
    ]
    const edges: Edge[] = vc.data.edges.map(e => {
      const s = EDGE_STYLE[e.verdict]
      const show = (e.verdict === "확인" || e.verdict === "부분") && e.lag != null
      return {
        id: `${e.from}-${e.to}`, source: e.from, target: e.to,
        label: show ? (e.lag === 0 ? "동행" : `${e.lag! > 0 ? "+" : "−"}${Math.abs(e.lag!)}M${e.lag_consistent ? "" : "?"}`) : undefined,
        labelStyle: { fontSize: 10 }, labelBgPadding: [3, 1] as [number, number],
        style: { stroke: s.stroke, strokeWidth: s.width, strokeDasharray: s.dash, opacity: e.from === selected || e.to === selected ? 1 : s.opacity },
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      }
    })
    return { nodes, edges }
  }, [vc.data, selected])

  const node = vc.data?.nodes.find(n => n.key === selected)

  return <PageLayout mode="document" header={<PageHeader title="밸류체인" description={`대만 월매출로 보는 공급 단계별 흐름과 한국 종목 · ${vc.data?.as_of ?? "-"} 공시 기준`} />}>
    <div className="space-y-5">
      {/* 번지는 중 */}
      {prop.isLoading ? <Skeleton className="h-40 w-full rounded-xl" />
        : prop.isError ? <ErrorState message="전파 판정을 불러오지 못했습니다." onRetry={() => void prop.refetch()} />
        : prop.data && <div className="grid gap-4 lg:grid-cols-3">
          <PropCard title="한국 확인 전" hint="대만은 오르는데 한국 수출·공시에는 아직 안 보인다 — 공시 시차의 빈칸" rows={prop.data.waiting} />
          <PropCard title="엇갈림" hint="원천끼리 방향이 반대 — 무엇이 맞는지 확인할 곳" rows={prop.data.diverging} />
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-card-title">선행 경보</CardTitle>
              <p className="text-caption text-muted-foreground">확인된 선행 엣지에서 앞선 칸이 방향을 바꿨다</p></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {!prop.data.leads.length ? <p className="text-muted-foreground">지금 방향을 바꾼 선행 칸이 없습니다.</p>
                : prop.data.leads.map(l => <Button variant="outline" key={`${l.leader}-${l.follower}`} onClick={() => select(l.follower)} className="block h-auto w-full whitespace-normal px-2 py-1.5 text-left text-sm font-normal">
                  <span className="font-medium">{l.leader_name}</span> {l.leader_state} → <span className="font-medium">{l.follower_name}</span> 약 {l.months}개월 뒤
                  <Badge variant={l.status === "대기" ? "default" : "secondary"} className="ml-1.5 text-[10px]">{l.status}</Badge>
                  {l.kr.length > 0 && <span className="block text-caption text-muted-foreground">한국: {l.kr.map(k => k.name).join("·")}</span>}
                </Button>)}
            </CardContent>
          </Card>
        </div>}

      {/* 지도 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-card-title">공급 지도</CardTitle>
          <p className="text-caption text-muted-foreground">
            왼쪽이 상류(장비·소재), 오른쪽이 최종 수요입니다. 칸 색 = 이번 달 3개월 YoY가 3개월 전보다 ±10%p(가속·둔화). 선 = 측정 판정
            (굵은 실선 확인 · 실선 부분 · 점선 미확인), 숫자 = 시차(+공급이 앞섬, −수요가 앞섬, ?는 두 신호 시차 불일치).
            {vc.data && ` 위약 기준 r>${vc.data.thresholds.yoy3m}(3개월 YoY Δ)·${vc.data.thresholds.yoy}(월 YoY Δ).`}
          </p>
        </CardHeader>
        <CardContent>
          {vc.isLoading ? <Skeleton className="h-[520px] w-full" />
            : vc.isError ? <ErrorState message="지도를 불러오지 못했습니다." onRetry={() => void vc.refetch()} />
            : !vc.data?.nodes.length ? <EmptyState message="지도 데이터가 없습니다." />
            : <div className="space-y-4">
              <div className="h-[680px] rounded-lg border">
                <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.02, minZoom: 0.65 }}
                  colorMode={resolvedTheme === "dark" ? "dark" : "light"} nodesDraggable={false} nodesConnectable={false} minZoom={0.2} maxZoom={2}
                  onNodeClick={(_, n) => select(n.id === selected ? null : n.id)} onPaneClick={() => select(null)} proOptions={{ hideAttribution: true }}>
                  <Background gap={20} size={1} />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </div>
              <NodePanel node={node} edges={vc.data.edges} nodes={vc.data.nodes} onSelect={select} />
            </div>}
        </CardContent>
      </Card>

      {/* 한국 확인 신호 전체 */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-card-title">한국 확인 신호</CardTitle>
          <p className="text-caption text-muted-foreground">대만 연결 · 한국 수출(HS, 확신도 상·중만 집계) · 공시 세 원천의 방향</p></CardHeader>
        <CardContent className="space-y-3">
          {confirms.isLoading ? <Skeleton className="h-32 w-full" />
            : confirms.isError ? <ErrorState message="확인 신호를 불러오지 못했습니다." onRetry={() => void confirms.refetch()} />
            : (confirms.data ?? []).map(c => <div key={c.stock_code} className="grid gap-2 border-b pb-3 last:border-b-0 md:grid-cols-[160px_minmax(0,1fr)]">
              <Link to={`/analyze/${c.stock_code}/summary`} className="font-medium hover:underline">
                {vc.data?.nodes.flatMap(n => n.kr).find(k => k.code === c.stock_code)?.name ?? c.stock_code}
              </Link>
              <KrConfirmStrip c={c} />
            </div>)}
        </CardContent>
      </Card>
    </div>
  </PageLayout>
}

function PropCard({ title, hint, rows }: { title: string; hint: string; rows: PropRow[] }) {
  return <Card>
    <CardHeader className="pb-2"><CardTitle className="text-card-title">{title} <span className="text-sm font-normal text-muted-foreground">{rows.length}</span></CardTitle>
      <p className="text-caption text-muted-foreground">{hint}</p></CardHeader>
    <CardContent className="space-y-1.5 text-sm">
      {!rows.length ? <p className="text-muted-foreground">해당 종목이 없습니다.</p> : rows.map(r => (
        <Link key={r.stock_code} to={`/analyze/${r.stock_code}/summary`} className="flex items-center gap-2 rounded-md px-1 py-1 hover:bg-muted/50">
          <span className="font-medium">{r.name}</span>
          <span className="ml-auto flex gap-2 text-caption tabular-nums">
            {(["taiwan", "trade", "disclosure"] as const).map(k => <span key={k} className={cn(r.directions[k] === "up" ? "text-up" : r.directions[k] === "down" ? "text-down" : "text-muted-foreground")}>
              {{ taiwan: "대만", trade: "수출", disclosure: "공시" }[k]} {r.directions[k] ? DIR[r.directions[k]!] : "-"}
            </span>)}
          </span>
        </Link>
      ))}
    </CardContent>
  </Card>
}

function NodePanel({ node, edges, nodes, onSelect }: { node?: VcNode; edges: VcEdge[]; nodes: VcNode[]; onSelect: (k: string) => void }) {
  if (!node) return <div className="rounded-lg border p-3 text-sm text-muted-foreground">칸을 누르면 구성 회사·한국 종목·앞뒤 칸과의 측정 결과가 여기 보입니다.</div>
  // 지도 아래 가로 배치 — 지도가 전체 폭을 쓰게
  const name = (k: string) => nodes.find(n => n.key === k)?.name ?? k
  const ups = edges.filter(e => e.to === node.key), downs = edges.filter(e => e.from === node.key)
  const EdgeLine = ({ e, other }: { e: VcEdge; other: string }) => <Button variant="ghost" onClick={() => onSelect(other)}
    className="block h-auto w-full whitespace-normal px-1 py-0.5 text-left text-caption font-normal" title={e.reason}>
    {name(other)} <span className="text-muted-foreground">· {e.verdict}{(e.verdict === "확인" || e.verdict === "부분") && e.lag != null ? ` · ${lagText(e.lag)}${e.lag_consistent ? "" : "(시차 불일치)"}` : ""}</span>
  </Button>
  return <div className="grid gap-4 rounded-lg border p-3 text-sm md:grid-cols-3">
    <div>
      <div className="flex items-center gap-2"><span className="font-semibold">{node.name}</span>{node.state && <Badge variant="outline" className="text-[11px]">{node.state}</Badge>}</div>
      <p className="text-caption text-muted-foreground">{node.description}</p>
      {node.tw.length > 0 && <p className="mt-1 text-caption tabular-nums">3M YoY {formatPercent(node.yoy_3m)} (3개월 전 {formatPercent(node.yoy_3m_prev)})</p>}
      {node.series.length > 1 && <div className="mt-1"><SparkLine data={node.series.map(p => p.yoy)} height={32} /></div>}
    </div>
    <div className="space-y-2">
      {node.tw.length > 0 && <div><p className="text-caption font-medium text-muted-foreground">대만 구성</p><p className="text-caption">{node.tw.map(t => t.name).join(" · ")}</p></div>}
      {node.kr.length > 0 && <div><p className="text-caption font-medium text-muted-foreground">한국 종목</p>
        <div className="flex flex-wrap gap-1.5">{node.kr.map(k => <Link key={k.code} to={`/analyze/${k.code}/summary`} className="text-caption text-primary hover:underline">{k.name}</Link>)}</div></div>}
    </div>
    <div className="space-y-2">
      {ups.length > 0 && <div><p className="text-caption font-medium text-muted-foreground">앞 칸(이 칸에 판다)</p>{ups.map(e => <EdgeLine key={e.from} e={e} other={e.from} />)}</div>}
      {downs.length > 0 && <div><p className="text-caption font-medium text-muted-foreground">다음 칸(이 칸이 판다)</p>{downs.map(e => <EdgeLine key={e.to} e={e} other={e.to} />)}</div>}
    </div>
  </div>
}
