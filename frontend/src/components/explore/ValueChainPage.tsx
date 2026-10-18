import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useTheme } from "next-themes"
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
import { formatPercent, formatUsd } from "@/utils/format"
import type { PropRow, UsMember, ValueChainResponse, VcDemand, VcEdge, VcNode } from "@/types"

/**
 * 탐색 › 밸류체인 (docs/specs/value-chain.md §5) — 최종 수요 → 대만 공급 단계 → 한국 종목.
 * 화면은 돈(주문)의 흐름으로 그린다: 왼쪽 최종 수요 → 오른쪽 상류(장비·소재). 저장된 엣지는 공급 방향(from이 to에 판다)이라 그릴 때 뒤집는다.
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

type ChainNodeData = { node?: VcNode; demand?: VcDemand; selected: boolean }
const stateTone = (s?: string | null) => !s ? "text-muted-foreground" : s === "가속" || s === "전환↑" ? "text-up" : s === "유지" ? "text-muted-foreground" : "text-down"

function ChainNode({ data }: NodeProps) {
  const d = data as unknown as ChainNodeData
  // 관측이 있는 수요는 실선(굵게), 관측이 없는 수요(PC)만 점선
  if (d.demand) return <div className={cn("w-[188px] rounded-md border-2 bg-card px-2 py-1.5 text-xs", d.demand.obs_label ? "" : "border-dashed",
    d.demand.state ? STATE_CLS[d.demand.state] : "", d.selected && "ring-2 ring-primary ring-offset-1 ring-offset-background")}>
    <Handle type="source" position={Position.Right} className="!opacity-0" />
    <div className="flex items-center gap-1">
      <span className="truncate font-semibold">{d.demand.name}</span>
      {d.demand.state && <span className={cn("ml-auto shrink-0 text-[10px]", stateTone(d.demand.state))}>{d.demand.state}</span>}
    </div>
    {d.demand.obs_label
      ? <div className="truncate text-[10px] tabular-nums text-muted-foreground" title={d.demand.obs_label}>분기 YoY {formatPercent(d.demand.yoy_3m)} · {d.demand.obs_label}</div>
      : <div className="truncate text-[10px] text-muted-foreground">{d.demand.description} · 대만 브랜드로 대리 관측</div>}
  </div>
  const n = d.node!
  const quarterly = n.freq === "Q"
  const krTrade = n.source === "kr_trade"
  const krOnly = !n.source           // 정말 관측이 없는 칸만 점선
  return <div className={cn("w-[188px] rounded-md border bg-card px-2 py-1.5 text-xs shadow-sm", n.state ? STATE_CLS[n.state] : "", krOnly && "border-dashed",
    d.selected && "ring-2 ring-primary ring-offset-1 ring-offset-background")}>
    <Handle type="target" position={Position.Left} className="!opacity-0" />
    <Handle type="source" position={Position.Right} className="!opacity-0" />
    <div className="flex items-center gap-1">
      <span className="truncate font-semibold">{n.name}</span>
      {n.state && <span className={cn("ml-auto shrink-0 text-[10px]", stateTone(n.state))}>{n.state}</span>}
    </div>
    <div className="text-[10px] tabular-nums text-muted-foreground">
      {krOnly ? "관측 없음" : quarterly ? `분기 YoY ${formatPercent(n.yoy_3m)} · 미국 실적` : krTrade ? `수출 3M YoY ${formatPercent(n.yoy_3m)} · 한국 HS` : `3M YoY ${formatPercent(n.yoy_3m)}`}
    </div>
    {n.kr.length > 0 && <div className="truncate text-[10px] font-medium text-primary">한국 {n.kr.map(k => k.name).join("·")}</div>}
  </div>
}
const nodeTypes = { chain: ChainNode, lane: LaneBand, tier: TierHeader }

/* 스윔레인 격자 — 열 = 단계(왼쪽 수요 → 오른쪽 상류), 행 = 수요처 레인. 같은 칸(단계·레인)에 여럿이면 세로로 쌓는다 */
const LANE_LABEL_W = 112
const COL_W = 232
const CELL_GAP = 12
const LANE_PAD = 34

function LaneBand({ data }: NodeProps) {
  const d = data as { label: string; width: number; height: number; shade: boolean }
  return <div style={{ width: d.width, height: d.height }} className={cn("pointer-events-none rounded-md border border-dashed", d.shade && "bg-muted/30")}>
    <div className="px-2 pt-1.5 text-[11px] font-semibold text-muted-foreground" style={{ width: LANE_LABEL_W }}>{d.label}</div>
  </div>
}
function TierHeader({ data }: NodeProps) {
  const d = data as { label: string }
  return <div style={{ width: NODE_W }} className="pointer-events-none border-b pb-1 text-center text-[11px] font-semibold text-muted-foreground">{d.label}</div>
}

function swimlane(vc: ValueChainResponse) {
  const tierIdx = Object.fromEntries(vc.tiers.map((t, i) => [t.key, i]))
  const keys = [...vc.demands.map(d => d.key), ...vc.nodes.map(n => n.key)]
  const cells: Record<string, string[]> = {}
  keys.forEach(k => { const c = vc.layout[k]; if (c) (cells[`${c.lane}|${c.tier}`] ??= []).push(k) })
  const pos: Record<string, { x: number; y: number }> = {}
  const bands: { key: string; label: string; y: number; height: number }[] = []
  let y = 0
  vc.lanes.forEach(lane => {
    const depth = Math.max(1, ...vc.tiers.map(t => cells[`${lane.key}|${t.key}`]?.length ?? 0))
    const height = LANE_PAD + depth * (NODE_H + CELL_GAP) + 8
    vc.tiers.forEach(t => (cells[`${lane.key}|${t.key}`] ?? []).forEach((k, i) => {
      pos[k] = { x: LANE_LABEL_W + tierIdx[t.key] * COL_W + 16, y: y + LANE_PAD + i * (NODE_H + CELL_GAP) }
    }))
    bands.push({ key: lane.key, label: lane.label, y, height })
    y += height + 10
  })
  return { pos, bands, width: LANE_LABEL_W + vc.tiers.length * COL_W + 16 }
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
    const { pos, bands, width } = swimlane(vc.data)
    const nodes: Node[] = [
      ...bands.map((b, i) => ({ id: `lane-${b.key}`, type: "lane", position: { x: 0, y: b.y }, draggable: false, selectable: false, zIndex: -1,
        data: { label: b.label, width, height: b.height, shade: i % 2 === 1 } })),
      ...vc.data.tiers.map((t, i) => ({ id: `tier-${t.key}`, type: "tier", position: { x: LANE_LABEL_W + i * COL_W + 16, y: -30 }, draggable: false, selectable: false,
        data: { label: t.label } })),
      ...vc.data.nodes.filter(n => pos[n.key]).map(n => ({ id: n.key, type: "chain", position: pos[n.key], data: { node: n, selected: n.key === selected } })),
      ...vc.data.demands.filter(d => pos[d.key]).map(d => ({ id: d.key, type: "chain", position: pos[d.key], data: { demand: d, selected: d.key === selected } })),
    ]
    const edges: Edge[] = vc.data.edges.map(e => {
      const s = EDGE_STYLE[e.verdict]
      const show = (e.verdict === "확인" || e.verdict === "부분") && e.lag != null
      return {
        id: `${e.from}-${e.to}`, source: e.to, target: e.from,
        label: show ? (e.lag === 0 ? "동행" : `${e.lag! > 0 ? "+" : "−"}${Math.abs(e.lag!)}M${e.lag_consistent ? "" : "?"}`) : undefined,
        labelStyle: { fontSize: 10 }, labelBgPadding: [3, 1] as [number, number],
        style: { stroke: s.stroke, strokeWidth: s.width, strokeDasharray: s.dash, opacity: e.from === selected || e.to === selected ? 1 : s.opacity },
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      }
    })
    return { nodes, edges }
  }, [vc.data, selected])

  const node = vc.data?.nodes.find(n => n.key === selected)
  const demand = vc.data?.demands.find(d => d.key === selected)

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
            열은 밸류체인 단계(왼쪽 최종 수요 → 오른쪽 소재·장비), 행은 수요처 레인입니다. 관측 원천: 대만 월매출 · 미국 분기 실적(수요·가속기) · 한국 수출 HS(한국 고유 칸), 점선은 관측 없음. 여러 수요에 함께 공급하는 칸은 '공통' 레인에 둡니다. 화살표는 주문과 돈이 흐르는 방향(사는 쪽 → 파는 쪽)입니다.
            칸 색 = 이번 달 3개월 YoY가 3개월 전보다 ±10%p(가속·둔화) — AI 데이터센터·스마트폰 수요와 AI 가속기는 미국 분기 실적(SEC)의 분기 YoY를 직전 분기와 비교. 선 = 측정 판정
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
                  onNodeClick={(_, n) => { if (n.type === "chain") select(n.id === selected ? null : n.id) }} onPaneClick={() => select(null)} proOptions={{ hideAttribution: true }}>
                  <Background gap={20} size={1} />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </div>
              {demand ? <DemandPanel demand={demand} edges={vc.data.edges} nodes={vc.data.nodes} onSelect={select} />
                : <NodePanel node={node} edges={vc.data.edges} nodes={vc.data.nodes} onSelect={select} />}
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
      {node.freq === "Q"
        ? <p className="mt-1 text-caption tabular-nums">분기 YoY {formatPercent(node.yoy_3m)} (직전 분기 {formatPercent(node.yoy_3m_prev)}) · {node.period} · {node.obs_label} (SEC 분기 실적)</p>
        : node.tw.length > 0 && <p className="mt-1 text-caption tabular-nums">3M YoY {formatPercent(node.yoy_3m)} (3개월 전 {formatPercent(node.yoy_3m_prev)}) · {node.period}</p>}
      {node.source === "kr_trade" && <p className="mt-1 text-caption tabular-nums">수출 3M YoY {formatPercent(node.yoy_3m)} (3개월 전 {formatPercent(node.yoy_3m_prev)}) · {node.period} · {node.obs_label}</p>}
      {node.series.length > 1 && <div className="mt-1"><SparkLine data={node.series.map(p => p.yoy)} height={32} /></div>}
      {!!node.us_members?.length && <UsMembers members={node.us_members} />}
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

/** 미국 수요 기업 최신 분기 — 회사·지표·분기·값·YoY */
function UsMembers({ members }: { members: UsMember[] }) {
  return <ul className="mt-2 divide-y text-caption">
    {members.map(m => <li key={m.ticker} className="flex items-baseline gap-2 py-1">
      <span className="shrink-0 font-medium">{m.name}</span><span className="min-w-0 truncate text-muted-foreground">{m.metric} · {m.q}</span>
      <span className="ml-auto tabular-nums">{formatUsd(m.value)}</span>
      <span className={cn("w-16 text-right tabular-nums", (m.yoy ?? 0) >= 0 ? "text-up" : "text-down")}>{formatPercent(m.yoy)}</span>
    </li>)}
  </ul>
}

/** 최종 수요 상세 — 관측 원천·회사별 최신 분기·분기 YoY 추이·이 수요에 파는 칸 */
function DemandPanel({ demand, edges, nodes, onSelect }: { demand: VcDemand; edges: VcEdge[]; nodes: VcNode[]; onSelect: (k: string) => void }) {
  const sellers = edges.filter(e => e.to === demand.key)
  return <div className="grid gap-4 rounded-lg border p-3 text-sm md:grid-cols-3">
    <div>
      <div className="flex items-center gap-2"><span className="font-semibold">{demand.name}</span>{demand.state && <Badge variant="outline" className="text-[11px]">{demand.state}</Badge>}</div>
      <p className="text-caption text-muted-foreground">{demand.description}</p>
      {demand.obs_label
        ? <p className="mt-1 text-caption tabular-nums">분기 YoY {formatPercent(demand.yoy_3m)} (직전 분기 {formatPercent(demand.yoy_3m_prev)}) · {demand.period} · {demand.obs_label} 합계 (SEC 분기 실적)</p>
        : <p className="mt-1 text-caption text-muted-foreground">직접 관측 원천이 없습니다 — 이 수요에 파는 대만 칸(PC 브랜드)이 대리 관측합니다.</p>}
      {(demand.series?.length ?? 0) > 1 && <div className="mt-1"><SparkLine data={demand.series!.map(p => p.yoy)} height={32} /></div>}
    </div>
    <div>{!!demand.us_members?.length && <><p className="text-caption font-medium text-muted-foreground">구성 회사 최신 분기</p><UsMembers members={demand.us_members} /></>}</div>
    <div>{sellers.length > 0 && <><p className="text-caption font-medium text-muted-foreground">이 수요에 파는 칸</p>
      {sellers.map(e => <Button key={e.from} variant="ghost" onClick={() => onSelect(e.from)} className="block h-auto w-full whitespace-normal px-1 py-0.5 text-left text-caption font-normal">
        {nodes.find(n => n.key === e.from)?.name ?? e.from} <span className="text-muted-foreground">· {e.verdict}</span>
      </Button>)}</>}</div>
  </div>
}
