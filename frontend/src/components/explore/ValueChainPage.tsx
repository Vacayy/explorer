import { useMemo } from "react"
import { Link, Navigate, useSearchParams } from "react-router-dom"
import { useTheme } from "next-themes"
import { ReactFlow, Background, BaseEdge, Controls, EdgeLabelRenderer, Handle, Position, MarkerType, getBezierPath, type Edge, type EdgeProps, type Node, type NodeProps } from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageLayout } from "@/components/shared/PageLayout"
import { HomeBlock } from "@/components/home/HomeSection"
import { BOUND_FIXED, BoundedArea } from "@/components/shared/Bounded"
import { SummaryStrip, SummaryStripSkeleton, type SummaryCell } from "@/components/industry/SummaryStrip"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { SparkLine } from "@/components/shared/Spark"
import { KrConfirmStrip } from "@/components/shared/TwLinkSignal"
import { MetricHint } from "@/components/shared/MetricHint"
import { Info, X } from "lucide-react"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { MAG_HINT, gravity, streamWidth } from "@/lib/valueChainMagnitude"
import { useKrConfirm, usePropagation, useValueChain, useValueChainExpectations, useValueChainFlow } from "@/hooks/useTwRevenue"
import { ExpGapCard, ExpectationPanel } from "@/components/explore/ValueChainExpectations"
import { ChainReportCard } from "@/components/explore/ChainReportCard"
import { useIsMobile } from "@/hooks/use-mobile"
import { cn } from "@/lib/utils"
import { formatLevel, formatNumber, formatPercent, formatRatio, formatSigma, formatUsd } from "@/utils/format"
import type { CustomerConcentration, ExpNode, FlowResponse, FlowRow, PropRow, UsMember, ValueChainResponse, VcAux, VcDemand, VcEdge, VcMarket, VcNode, VcPxq } from "@/types"

/**
 * 탐색 › 밸류체인 (docs/specs/value-chain.md §5) — 최종 수요 → 대만 공급 단계 → 한국 종목.
 * 화면은 돈(주문)의 흐름으로 그린다: 왼쪽 최종 수요 → 오른쪽 상류(장비·소재). 저장된 엣지는 공급 방향(from이 to에 판다)이라 그릴 때 뒤집는다.
 * 위: 번지는 중(한국 확인 전·엇갈림·선행 경보). 가운데: 지도(노드 = 이번 달 상태, 엣지 = 측정 판정·시차). 아래: 한국 확인 신호 전체.
 * 선택한 노드는 URL node. 예측력은 '대만은 매달, 한국은 분기'라는 공시 시차에서 나온다(D-251).
 */

const NODE_W = 200
const NODE_H = 66
const STATE_CLS: Record<string, string> = {
  "가속": "border-up/60 bg-up/5", "전환↑": "border-up/60 bg-up/5",
  "둔화": "border-down/60 bg-down/5", "전환↓": "border-down/60 bg-down/5", "유지": "border-border",
}
const DIR: Record<string, string> = { up: "↑", down: "↓", flat: "→" }
const lagText = (lag: number | null | undefined) => lag == null ? "" : lag === 0 ? "동행" : lag > 0 ? `공급 ${lag}개월 앞섬` : `수요 ${-lag}개월 앞섬`

type ChainNodeData = { node?: VcNode; demand?: VcDemand; selected: boolean; mag?: { level: number | null; dia: number | null; note?: string | null } }

/** 칸의 중력(§14) — 원 지름 = 규모(로그), 아래 금액. 규모를 모르면 점선 빈 원 */
function Gravity({ mag }: { mag?: ChainNodeData["mag"] }) {
  if (!mag) return null
  return <div className="flex w-9 shrink-0 flex-col items-center justify-center gap-0.5" title={mag.level ? `최근 3개월(분기 칸은 최신 분기) 규모 ${formatUsd(mag.level)}` : mag.note ?? "규모 없음 — 매출·수출액 원천이 없거나 이력이 부족"}>
    {mag.dia ? <span className="rounded-full bg-chart-blue/70" style={{ width: mag.dia, height: mag.dia }} />
      : <span className="size-3 rounded-full border border-dashed border-muted-foreground" />}
    <span className="text-[9px] leading-none tabular-nums text-muted-foreground">{mag.level ? formatUsd(mag.level) : "-"}</span>
  </div>
}

/** 물줄기 선 — 굵기 = 추정 증가액, 마우스를 올리면 금액·추정 근거 */
function StreamEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, label, data }: EdgeProps) {
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  return <>
    <g><title>{(data as { tip?: string } | undefined)?.tip}</title><BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} interactionWidth={18} /></g>
    {label && <EdgeLabelRenderer>
      <div style={{ position: "absolute", transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }} className="nodrag nopan rounded bg-background/90 px-1 text-[10px] tabular-nums text-foreground">{label}</div>
    </EdgeLabelRenderer>}
  </>
}
const edgeTypes = { stream: StreamEdge }
const stateTone = (s?: string | null) => !s ? "text-muted-foreground" : s === "가속" || s === "전환↑" ? "text-up-ink" : s === "유지" ? "text-muted-foreground" : "text-down-ink"

function ChainNode({ data }: NodeProps) {
  const d = data as unknown as ChainNodeData
  // 관측이 있는 수요는 실선(굵게), 관측이 없는 수요(PC)만 점선
  if (d.demand) return <div className={cn("flex w-[200px] gap-1.5 rounded-card border-2 bg-card px-2 py-1.5 text-xs", d.demand.obs_label ? "" : "border-dashed",
    d.demand.state ? STATE_CLS[d.demand.state] : "", d.selected && "ring-2 ring-primary ring-offset-1 ring-offset-background")}>
    <Handle type="target" position={Position.Left} className="!opacity-0" />
    <Handle type="source" position={Position.Right} className="!opacity-0" />
    <Gravity mag={d.mag} />
    <div className="min-w-0 flex-1">
    <div className="flex items-center gap-1">
      <span className="truncate font-semibold">{d.demand.name}</span>
      {d.demand.state && <span className={cn("ml-auto shrink-0 text-[10px]", stateTone(d.demand.state))}>{d.demand.state}</span>}
    </div>
    {d.demand.obs_label
      ? <div className="truncate text-[10px] tabular-nums text-muted-foreground" title={d.demand.obs_label}>{d.demand.freq === "M" ? "3M" : "분기"} YoY {formatPercent(d.demand.yoy_3m)} · {d.demand.obs_label}</div>
      : <div className="truncate text-[10px] text-muted-foreground">{d.demand.description} · 대만 브랜드로 대리 관측</div>}
    </div>
  </div>
  const n = d.node!
  const quarterly = n.freq === "Q"
  const krTrade = n.source === "kr_trade"
  const krOnly = !n.source           // 정말 관측이 없는 칸만 점선
  return <div className={cn("flex w-[200px] gap-1.5 rounded-card border bg-card px-2 py-1.5 text-xs", n.state ? STATE_CLS[n.state] : "", krOnly && "border-dashed",
    d.selected && "ring-2 ring-primary ring-offset-1 ring-offset-background")}>
    <Handle type="target" position={Position.Left} className="!opacity-0" />
    <Handle type="source" position={Position.Right} className="!opacity-0" />
    <Gravity mag={d.mag} />
    <div className="min-w-0 flex-1">
    <div className="flex items-center gap-1">
      <span className="truncate font-semibold">{n.name}</span>
      {n.state && <span className={cn("ml-auto shrink-0 text-[10px]", stateTone(n.state))}>{n.state}</span>}
    </div>
    <div className="text-[10px] tabular-nums text-muted-foreground">
      {krOnly ? "관측 없음" : quarterly ? `분기 YoY ${formatPercent(n.yoy_3m)} · ${n.key === "jp_backend" ? "IR 실적" : "미국 실적"}` : krTrade ? `수출 3M YoY ${formatPercent(n.yoy_3m)} · 한국 HS`
        : n.source === "ext" ? `3M YoY ${formatPercent(n.yoy_3m)} · 무역통계` : `3M YoY ${formatPercent(n.yoy_3m)}`}
    </div>
    {n.kr.length > 0 && <div className="truncate text-[10px] font-medium text-primary">한국 {n.kr.map(k => k.name).join("·")}</div>}
    </div>
  </div>
}
const nodeTypes = { chain: ChainNode, lane: LaneBand, tier: TierHeader }

/* 스윔레인 격자 — 열 = 단계(왼쪽 수요 → 오른쪽 상류), 행 = 수요처 레인. 같은 칸(단계·레인)에 여럿이면 세로로 쌓는다 */
const LANE_LABEL_W = 112
const COL_W = 244
const CELL_GAP = 12
const LANE_PAD = 34

function LaneBand({ data }: NodeProps) {
  const d = data as { label: string; width: number; height: number; shade: boolean }
  return <div style={{ width: d.width, height: d.height }} className={cn("pointer-events-none rounded-card border border-dashed", d.shade && "bg-muted/30")}>
    <div className="px-2 pt-1.5 text-[11px] font-semibold text-muted-foreground" style={{ width: LANE_LABEL_W }}>{d.label}</div>
  </div>
}
function TierHeader({ data }: NodeProps) {
  const d = data as { label: string; width?: number }
  return <div style={{ width: d.width ?? NODE_W }} className="pointer-events-none border-b pb-1 text-center text-[11px] font-semibold text-muted-foreground">{d.label}</div>
}

const MAX_STACK = 6   // 한 칸(단계·레인)에 이보다 많으면 그 열 안에서 옆으로 한 줄 더 쌓는다

function swimlane(vc: ValueChainResponse) {
  const keys = [...vc.demands.map(d => d.key), ...vc.nodes.map(n => n.key)]
  const cells: Record<string, string[]> = {}
  keys.forEach(k => { const c = vc.layout[k]; if (c) (cells[`${c.lane}|${c.tier}`] ??= []).push(k) })
  // 열 폭 = 그 단계에서 가장 많이 쌓인 칸의 줄 수
  const subCols = Object.fromEntries(vc.tiers.map(t => [t.key,
    Math.max(1, ...vc.lanes.map(l => Math.ceil((cells[`${l.key}|${t.key}`]?.length ?? 0) / MAX_STACK)))]))
  const tierX: Record<string, number> = {}
  let x = LANE_LABEL_W + 16
  vc.tiers.forEach(t => { tierX[t.key] = x; x += subCols[t.key] * COL_W })
  const pos: Record<string, { x: number; y: number }> = {}
  const bands: { key: string; label: string; y: number; height: number }[] = []
  let y = 0
  vc.lanes.forEach(lane => {
    const depth = Math.max(1, ...vc.tiers.map(t => Math.min(MAX_STACK, cells[`${lane.key}|${t.key}`]?.length ?? 0)))
    const height = LANE_PAD + depth * (NODE_H + CELL_GAP) + 8
    vc.tiers.forEach(t => (cells[`${lane.key}|${t.key}`] ?? []).forEach((k, i) => {
      pos[k] = { x: tierX[t.key] + Math.floor(i / MAX_STACK) * COL_W, y: y + LANE_PAD + (i % MAX_STACK) * (NODE_H + CELL_GAP) }
    }))
    bands.push({ key: lane.key, label: lane.label, y, height })
    y += height + 10
  })
  return { pos, bands, width: x, tierX, subCols }
}

const LABEL_TOP = 8   // 금액 라벨을 다는 굵은 선 수

export default function ValueChainPage() {
  const vc = useValueChain()
  const prop = usePropagation()
  const confirms = useKrConfirm()
  const flow = useValueChainFlow()
  const exp = useValueChainExpectations()
  const [params, setParams] = useSearchParams()
  const { resolvedTheme } = useTheme()
  const isMobile = useIsMobile()
  const selected = params.get("node")
  const view = params.get("view") === "lines" ? "lines" : "grid"
  const setParam = (k: string, v: string | null) => setParams(prev => { const n = new URLSearchParams(prev); if (v) n.set(k, v); else n.delete(k); return n }, { replace: true, preventScrollReset: true })
  // 금액 규모(§14) — 칸 규모·선별 추정 증가액. 흐름 API가 실패해도 지도는 그대로 그린다
  const mag = useMemo(() => {
    const level: Record<string, number | null> = {}
    flow.data?.nodes.forEach(r => { level[r.key] = r.level_usd ?? null })
    flow.data?.demands?.forEach(d => { level[d.key] = d.level_usd })
    const flows = flow.data?.edge_flows ?? []
    const known = Object.values(level).filter((v): v is number => !!v && v > 0)
    return { level, flows, byEdge: Object.fromEntries(flows.map(f => [`${f.from}-${f.to}`, f])),
      min: known.length ? Math.min(...known) : 0, max: known.length ? Math.max(...known) : 0,
      maxFlow: Math.max(0, ...flows.map(f => f.flow_usd ?? 0)), hasAny: known.length > 0 }
  }, [flow.data])
  // 칸을 바꾸면 보고서 선택(report)은 그 칸 기준으로 다시 고른다
  const select = (k: string | null) => setParams(prev => { const n = new URLSearchParams(prev); if (k) n.set("node", k); else n.delete("node"); n.delete("report"); return n }, { replace: true, preventScrollReset: true })
  const reportId = params.get("report") ? Number(params.get("report")) : null

  const graph = useMemo(() => {
    if (!vc.data) return { nodes: [] as Node[], edges: [] as Edge[], demandX: 0 }
    const { pos, bands, width, tierX, subCols } = swimlane(vc.data)
    const magOf = (k: string) => flow.data ? { level: mag.level[k] ?? null, dia: gravity(mag.level[k], mag.min, mag.max),
      note: flow.data.demands?.find(d => d.key === k)?.level_note } : undefined
    const nodes: Node[] = [
      ...bands.map((b, i) => ({ id: `lane-${b.key}`, type: "lane", position: { x: 0, y: b.y }, draggable: false, selectable: false, zIndex: -1,
        data: { label: b.label, width, height: b.height, shade: i % 2 === 1 } })),
      ...vc.data.tiers.map(t => ({ id: `tier-${t.key}`, type: "tier", position: { x: tierX[t.key], y: -30 }, draggable: false, selectable: false,
        data: { label: t.label, width: subCols[t.key] * COL_W - (COL_W - NODE_W) } })),
      ...vc.data.nodes.filter(n => pos[n.key]).map(n => ({ id: n.key, type: "chain", position: pos[n.key], data: { node: n, selected: n.key === selected, mag: magOf(n.key) } })),
      ...vc.data.demands.filter(d => pos[d.key]).map(d => ({ id: d.key, type: "chain", position: pos[d.key], data: { demand: d, selected: d.key === selected, mag: magOf(d.key) } })),
    ]
    const top = new Set([...mag.flows].filter(f => (f.flow_usd ?? 0) > 0).sort((a, b) => b.flow_usd! - a.flow_usd!).slice(0, LABEL_TOP).map(f => `${f.from}-${f.to}`))
    const name = (k: string) => vc.data!.nodes.find(n => n.key === k)?.name ?? vc.data!.demands.find(d => d.key === k)?.name ?? k
    const edges: Edge[] = vc.data.edges.map(e => {
      const id = `${e.from}-${e.to}`
      const f = mag.byEdge[id]?.flow_usd
      const up = (f ?? 0) > 0
      const lag = (e.verdict === "확인" || e.verdict === "부분") && e.lag != null ? (e.lag === 0 ? "동행" : `${e.lag! > 0 ? "+" : "−"}${Math.abs(e.lag!)}M${e.lag_consistent ? "" : "?"}`) : null
      const amt = top.has(id) ? `+${formatUsd(f!)}` : null
      const near = e.from === selected || e.to === selected
      return {
        id, source: e.to, target: e.from, type: "stream",
        label: [amt, lag].filter(Boolean).join(" · ") || undefined,
        data: { tip: `${name(e.to)} → ${name(e.from)} (${e.reason})\n추정 증가액 ${f == null ? "알 수 없음" : `${f > 0 ? "+" : "−"}${formatUsd(Math.abs(f))}`} · 시차 판정 ${e.verdict}\n${MAG_HINT}` },
        style: { stroke: up ? "var(--color-chart-blue)" : "var(--muted-foreground)", strokeWidth: streamWidth(f, mag.maxFlow),
          opacity: near ? 0.95 : up ? 0.5 : 0.3 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: up ? "var(--color-chart-blue)" : "var(--muted-foreground)" },
      }
    })
    return { nodes, edges, demandX: tierX.demand ?? 0 }
  }, [vc.data, selected, mag])

  const node = vc.data?.nodes.find(n => n.key === selected)
  const demand = vc.data?.demands.find(d => d.key === selected)
  // 지운 보기(물줄기 ?view=sankey, D-319)는 기본 지도로 — 그 보기 전용 ?lane=도 버린다
  const rawView = params.get("view")
  if (rawView && rawView !== "lines") {
    const rest = new URLSearchParams(params); rest.delete("view"); rest.delete("lane")
    return <Navigate to={`/value-chain${rest.size ? `?${rest}` : ""}`} replace />
  }

  return <PageLayout mode="document">
    <div className="surface-stack flex flex-col">
      {vc.data ? <SummaryStrip label="valuechain" cells={vcSummary(vc.data)} /> : vc.isLoading ? <SummaryStripSkeleton /> : null}
      {/* 밸류체인 지도 — 행 = 단계, 열 = 수요 갈래(§4.8b). 옛 연결선 지도는 보기 전환으로(물줄기는 지웠다, D-319) */}
      <HomeBlock label="vc.map" title="밸류체인 지도" info={MAP_INFO} asOf={vc.data?.as_of ? `${vc.data.as_of} 공시` : null}
        actions={<ToggleGroup type="single" size="sm" variant="outline" value={view} onValueChange={v => v && setParam("view", v === "grid" ? null : v)} aria-label="보기">
          <ToggleGroupItem value="grid" className="px-2.5 text-xs">지도</ToggleGroupItem>
          <ToggleGroupItem value="lines" className="px-2.5 text-xs">연결선</ToggleGroupItem>
        </ToggleGroup>}>
        {vc.isLoading ? <Skeleton className={cn("w-full", BOUND_FIXED.lg)} />
          : vc.isError ? <ErrorState message="지도를 불러오지 못했습니다." onRetry={() => void vc.refetch()} />
          : !vc.data?.nodes.length ? <EmptyState message="지도 데이터가 없습니다." />
          : <div className="space-y-4">
            {view === "grid" ? <>
              <StateLegend />
              {/* 상세 패널은 지도 칸이 넉넉할 때(컨테이너 66rem 이상)만 오른쪽, 아니면 지도 아래 */}
              <div className="@container"><div className={cn("grid items-start gap-3", selected && !isMobile && "@min-[66rem]:grid-cols-[minmax(0,1fr)_340px]")}>
                {/* 지도·상세는 상한(lg) 안에서 스크롤 — 칸을 골라도 블록 높이가 크게 바뀌지 않게 */}
                <BoundedArea size="lg"><VcGrid vc={vc.data} selected={selected} onSelect={k => select(k === selected ? null : k)} /></BoundedArea>
                {selected && !isMobile && <BoundedArea size="lg"><DetailPanel vc={vc.data} node={node} demand={demand} onSelect={select} exp={exp.data?.as_of ? exp.data.nodes[selected] : undefined} expAsOf={exp.data?.as_of ?? null} compact /></BoundedArea>}
              </div></div>
            </> : <>
              {flow.isError ? <p className="text-caption text-destructive">금액 규모를 불러오지 못해 원·굵기 없이 그렸습니다.</p>
                : flow.data && !mag.hasAny && <p className="text-caption text-muted-foreground">규모 데이터가 없어 원·굵기 없이 그렸습니다.</p>}
              <div className="h-[480px] rounded-card border md:h-[680px]">
                  {/* <768: 전체 맞춤은 글자를 읽을 수 없을 만큼 작아져, 최종 수요 열에서 읽을 수 있는 배율로 시작하고 끌어서 따라간다 */}
                  <ReactFlow key={isMobile ? "m" : "d"} nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
                    {...(isMobile ? { defaultViewport: { x: 8 - graph.demandX * 0.6, y: 28, zoom: 0.6 } } : { fitView: true, fitViewOptions: { padding: 0.02, minZoom: 0.65 } })}
                    colorMode={resolvedTheme === "dark" ? "dark" : "light"} nodesDraggable={false} nodesConnectable={false} minZoom={0.2} maxZoom={2}
                    onNodeClick={(_, n) => { if (n.type === "chain") select(n.id === selected ? null : n.id) }} onPaneClick={() => select(null)} proOptions={{ hideAttribution: true }}>
                    <Background gap={20} size={1} />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </div>
              {!isMobile && (selected ? <DetailPanel vc={vc.data} node={node} demand={demand} onSelect={select} exp={exp.data?.as_of ? exp.data.nodes[selected] : undefined} expAsOf={exp.data?.as_of ?? null} />
                : <p role="status" className="text-sm text-muted-foreground">칸을 누르면 구성 회사·한국 종목·앞뒤 칸과의 측정 결과가 보입니다.</p>)}
            </>}
          </div>}
      </HomeBlock>

      {/* 최종 수요 관측 — 비상장 수요는 계약 상대의 숫자로 본다 */}
      {vc.data && <HomeBlock label="vc.demand" title="최종 수요 관측" info="최종 수요를 무엇으로 관측하는지와 3개월 전년 대비입니다. 비상장 수요(AI 프론티어 랩)는 계약 상대(오라클·코어위브)의 수주잔고로 봅니다." bodyClassName="p-0">
        <DemandTable demands={vc.data.demands} onSelect={select} />
      </HomeBlock>}
      {/* 돈의 흐름 — 지금 어디로 가장 많이 흐르고, 다음 스포트라이트는 어디일 수 있나(가설) */}
      {flow.isLoading ? <Skeleton className="h-48 w-full rounded-card" />
        : flow.isError ? <ErrorState message="흐름 분석을 불러오지 못했습니다." onRetry={() => void flow.refetch()} />
        : flow.data && <FlowCard data={flow.data} onSelect={select} />}
      {/* 사실 vs 기대 — 관측과 애널리스트 컨센서스의 차이(§15) */}
      {exp.isLoading ? <Skeleton className="h-36 w-full rounded-card" />
        : exp.isError ? <ErrorState message="시장 기대치를 불러오지 못했습니다." onRetry={() => void exp.refetch()} />
        : exp.data?.as_of ? <ExpGapCard data={exp.data} onSelect={select} />
        : <EmptyState message="시장 기대치 스냅샷이 아직 없습니다 — 매일 08:10 수집 뒤 채워집니다." />}
      {/* 번지는 중 */}
      {prop.isLoading ? <Skeleton className="h-40 w-full rounded-card" />
        : prop.isError ? <ErrorState message="전파 판정을 불러오지 못했습니다." onRetry={() => void prop.refetch()} />
        : prop.data && <div className="surface-grid grid lg:grid-cols-3">
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

      {/* 트리 보고서 — 고른 공급 칸(없거나 수요 칸이면 메모리)에서 수요 쪽으로 타고 올라간다(§16, bottom-up) */}
      {vc.data && <ChainReportCard root={node?.key ?? "memory"} rootName={node?.name ?? vc.data.nodes.find(n => n.key === "memory")?.name ?? "메모리"}
        pickedDemand={demand?.name ?? null} reportId={reportId} onReport={id => setParam("report", id == null ? null : String(id))}
        outline={params.get("outline") === "top_down" ? "top_down" : "bottom_up"} onOutline={o => setParam("outline", o === "bottom_up" ? null : o)} />}

      {/* 한국 확인 신호 전체 */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-card-title">한국 확인 신호</CardTitle>
          <p className="text-caption text-muted-foreground">대만 연결 · 한국 수출(HS, 확신도 상·중만 집계) · 공시 세 원천의 방향</p></CardHeader>
        <CardContent><BoundedArea size="md" viewportClassName="[&>div]:space-y-3">
          {confirms.isLoading ? <Skeleton className="h-32 w-full" />
            : confirms.isError ? <ErrorState message="확인 신호를 불러오지 못했습니다." onRetry={() => void confirms.refetch()} />
            : (confirms.data ?? []).map(c => <div key={c.stock_code} className="grid gap-2 border-b pb-3 last:border-b-0 md:grid-cols-[160px_minmax(0,1fr)]">
              <Link to={`/analyze/${c.stock_code}/summary`} className="font-medium hover:underline">
                {vc.data?.nodes.flatMap(n => n.kr).find(k => k.code === c.stock_code)?.name ?? c.stock_code}
              </Link>
              <KrConfirmStrip c={c} />
            </div>)}
        </BoundedArea></CardContent>
      </Card>
    </div>
    {/* 모바일 — 노드 상세는 아래에서 올라오는 시트(§4.29) */}
    {isMobile && vc.data && <Sheet open={!!selected && (!!node || !!demand)} onOpenChange={v => { if (!v) select(null) }}>
      <SheetContent side="bottom" className="max-h-[85dvh] overflow-y-auto">
        <SheetHeader className="pb-0"><SheetTitle>{node?.name ?? demand?.name}</SheetTitle><SheetDescription className="sr-only">밸류체인 칸 상세</SheetDescription></SheetHeader>
        <div className="px-4 pb-6"><DetailPanel vc={vc.data} node={node} demand={demand} onSelect={select} exp={selected && exp.data?.as_of ? exp.data.nodes[selected] : undefined} expAsOf={exp.data?.as_of ?? null} compact bare /></div>
      </SheetContent>
    </Sheet>}
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
            {(["taiwan", "trade", "disclosure"] as const).map(k => <span key={k} className={cn(r.directions[k] === "up" ? "text-up-ink" : r.directions[k] === "down" ? "text-down-ink" : "text-muted-foreground")}>
              {{ taiwan: "대만", trade: "수출", disclosure: "공시" }[k]} {r.directions[k] ? DIR[r.directions[k]!] : "-"}
            </span>)}
          </span>
        </Link>
      ))}
    </CardContent>
  </Card>
}

function NodePanel({ node, edges, nodes, demands, onSelect, compact }: { node?: VcNode; edges: VcEdge[]; nodes: VcNode[]; demands: VcDemand[]; onSelect: (k: string) => void; compact?: boolean }) {
  if (!node) return <div className="rounded-card border p-3 text-sm text-muted-foreground">칸을 누르면 구성 회사·한국 종목·앞뒤 칸과의 측정 결과가 여기 보입니다.</div>
  // 지도 아래 가로 배치 — 지도가 전체 폭을 쓰게
  const name = (k: string) => nodes.find(n => n.key === k)?.name ?? demands.find(d => d.key === k)?.name ?? k
  const ups = edges.filter(e => e.to === node.key), downs = edges.filter(e => e.from === node.key)
  const EdgeLine = ({ e, other }: { e: VcEdge; other: string }) => <Button variant="ghost" onClick={() => onSelect(other)}
    className="block h-auto w-full whitespace-normal px-1 py-0.5 text-left text-caption font-normal" title={e.reason}>
    {name(other)} <span className="text-muted-foreground">· {e.verdict}{(e.verdict === "확인" || e.verdict === "부분") && e.lag != null ? ` · ${lagText(e.lag)}${e.lag_consistent ? "" : "(시차 불일치)"}` : ""}</span>
  </Button>
  return <div className={cn("grid gap-4 text-sm", !compact && "md:grid-cols-3")}>
    <div>
      <div className="flex items-center gap-2"><span className="font-semibold">{node.name}</span>{node.state && <Badge variant="outline" className="text-[11px]">{node.state}</Badge>}
        {node.state_z != null && <span className="text-caption tabular-nums text-muted-foreground" title="성장률 변화가 이 칸의 평소 변동(표준편차)의 몇 배인지 — ±1σ 이상이면 가속·둔화">평소 변동 대비 {formatSigma(node.state_z)}</span>}
        {node.obs_kind === "proxy" && <Badge variant="secondary" className="text-[11px]">대리 관측</Badge>}</div>
      <p className="text-caption text-muted-foreground">{node.description}</p>
      {node.obs_caveat && <p className="mt-1 text-caption text-muted-foreground">{node.obs_caveat}</p>}
      {node.freq === "Q"
        ? <p className="mt-1 text-caption tabular-nums">분기 YoY {formatPercent(node.yoy_3m)} (직전 분기 {formatPercent(node.yoy_3m_prev)}) · {node.period} · {node.obs_label} (SEC 분기 실적)</p>
        : node.tw.length > 0 && <p className="mt-1 text-caption tabular-nums">3M YoY {formatPercent(node.yoy_3m)} (3개월 전 {formatPercent(node.yoy_3m_prev)}) · {node.period}</p>}
      {node.source === "ext" && <p className="mt-1 text-caption tabular-nums">3M YoY {formatPercent(node.yoy_3m)} (3개월 전 {formatPercent(node.yoy_3m_prev)}) · {node.period} · {node.obs_label}</p>}
      {node.source === "kr_trade" && <p className="mt-1 text-caption tabular-nums">수출 3M YoY {formatPercent(node.yoy_3m)} (3개월 전 {formatPercent(node.yoy_3m_prev)}) · {node.period} · {node.obs_label}</p>}
      {node.series.length > 1 && <div className="mt-1"><SparkLine data={node.series.map(p => p.yoy)} height={32} /></div>}
      {!!node.us_members?.length && <UsMembers members={node.us_members} />}
      {!!node.aux?.length && <AuxList aux={node.aux} />}
      {!!node.market?.length && <MarketList market={node.market} />}
      {!!node.pxq?.length && <PxqList pxq={node.pxq} />}
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
    {members.map(m => <li key={m.ticker} className="flex flex-wrap items-baseline gap-x-2 py-1">
      <span className="shrink-0 font-medium">{m.name}</span><span className="min-w-0 truncate text-muted-foreground">{m.metric} · {m.q}</span>
      <span className="ml-auto tabular-nums">{formatUsd(m.value)}</span>
      {m.qoq_delta != null && <span className="w-20 text-right tabular-nums text-muted-foreground" title="전 분기 대비 순증가">
        {m.qoq_delta >= 0 ? "+" : "−"}{formatUsd(Math.abs(m.qoq_delta))} QoQ</span>}
      <span className={cn("w-16 text-right tabular-nums", (m.yoy ?? 0) >= 0 ? "text-up-ink" : "text-down-ink")}>{formatPercent(m.yoy)}</span>
      {m.customers && <CustomerLine c={m.customers} />}
    </li>)}
  </ul>
}

/** 10% 이상 고객 비중 한 줄 — 최신 기간 고객별 비중 + 분기 최대 고객 비중 추이(집중도가 풀리는지·쏠리는지) */
function CustomerLine({ c }: { c: CustomerConcentration }) {
  const trend = c.top_trend.map(p => formatRatio(p.top_pct)).join(" → ")
  return <span className="basis-full pl-2 text-muted-foreground">
    10% 이상 고객({c.period_kind === "Q" ? "분기" : "연간"} {c.period_end}): {c.customers.map(x => x.label ? `${x.label} ${formatRatio(x.pct)}` : formatRatio(x.pct)).join(" · ")}
    {c.top_trend.length > 1 && <span title="분기별 최대 고객 비중"> · 최대 고객 {trend}</span>}
  </span>
}

/** 최종 수요 상세 — 관측 원천·회사별 최신 분기·분기 YoY 추이·이 수요에 파는 칸 */
function DemandPanel({ demand, edges, nodes, onSelect, compact }: { demand: VcDemand; edges: VcEdge[]; nodes: VcNode[]; onSelect: (k: string) => void; compact?: boolean }) {
  const sellers = edges.filter(e => e.to === demand.key)
  return <div className={cn("grid gap-4 text-sm", !compact && "md:grid-cols-3")}>
    <div>
      <div className="flex items-center gap-2"><span className="font-semibold">{demand.name}</span>{demand.state && <Badge variant="outline" className="text-[11px]">{demand.state}</Badge>}</div>
      <p className="text-caption text-muted-foreground">{demand.description}</p>
      {demand.obs_label
        ? demand.freq === "M"
          ? <p className="mt-1 text-caption tabular-nums">3M YoY {formatPercent(demand.yoy_3m)} (3개월 전 {formatPercent(demand.yoy_3m_prev)}) · {demand.period} · {demand.obs_label}</p>
          : <p className="mt-1 text-caption tabular-nums">분기 YoY {formatPercent(demand.yoy_3m)} (직전 분기 {formatPercent(demand.yoy_3m_prev)}) · {demand.period} · {demand.obs_label} 합계 (SEC 분기 실적)</p>
        : <p className="mt-1 text-caption text-muted-foreground">직접 관측 원천이 없습니다 — 이 수요에 파는 대만 칸(PC 브랜드)이 대리 관측합니다.</p>}
      {(demand.series?.length ?? 0) > 1 && <div className="mt-1"><SparkLine data={demand.series!.map(p => p.yoy)} height={32} /></div>}
    </div>
    <div>{!!demand.us_members?.length && <><p className="text-caption font-medium text-muted-foreground">구성 회사 최신 분기</p><UsMembers members={demand.us_members} /></>}
      {!!demand.aux?.length && <AuxList aux={demand.aux} />}</div>
    <div>{sellers.length > 0 && <><p className="text-caption font-medium text-muted-foreground">이 수요에 파는 칸</p>
      {sellers.map(e => <Button key={e.from} variant="ghost" onClick={() => onSelect(e.from)} className="block h-auto w-full whitespace-normal px-1 py-0.5 text-left text-caption font-normal">
        {nodes.find(n => n.key === e.from)?.name ?? e.from} <span className="text-muted-foreground">· {e.verdict}</span>
      </Button>)}</>}</div>
  </div>
}

/** 교차 확인 지표 — 같은 흐름을 다른 원천(월간)에서 본 3개월 YoY·상태 */
function AuxList({ aux }: { aux: VcAux[] }) {
  return <div className="mt-3">
    <p className="text-caption font-medium text-muted-foreground">교차 확인 지표</p>
    <ul className="divide-y text-caption">
      {aux.map(a => <li key={a.series} className="flex items-baseline gap-2 py-1">
        <span className="min-w-0 flex-1">{a.note
          ? <MetricHint hint={a.note}><span className="underline decoration-dotted underline-offset-2">{a.label}</span> <Info className="inline size-3 text-muted-foreground" /></MetricHint>
          : a.label}</span>
        {a.missing ? <span className="text-muted-foreground">수집 전</span> : <>
          <span className="shrink-0 tabular-nums text-muted-foreground">{a.period}</span>
          <span className={cn("shrink-0 tabular-nums", stateTone(a.state))}>3M YoY {formatPercent(a.yoy_3m)}</span>
          {a.state && <Badge variant="outline" className="shrink-0 px-1 text-[10px]">{a.state}</Badge>}
        </>}
      </li>)}
    </ul>
  </div>
}

/** 신용·금리 여건 — 스프레드·금리가 오르면 조달이 어려워진다(긴축) */
function MarketList({ market }: { market: VcMarket[] }) {
  const tone = (s?: string | null) => s === "긴축" ? "text-down-ink" : s === "완화" ? "text-up-ink" : "text-muted-foreground"
  return <div className="mt-3">
    <p className="text-caption font-medium text-muted-foreground">신용·금리 여건</p>
    <ul className="divide-y text-caption">
      {market.map(m => <li key={m.ref} className="flex items-baseline gap-2 py-1">
        <span className="min-w-0 flex-1">{m.label}</span>
        {m.missing ? <span className="text-muted-foreground">데이터 없음</span> : <>
          <span className="shrink-0 tabular-nums">{m.unit === "%" ? `${formatLevel(m.value)}%` : `${formatNumber(Math.round(m.value ?? 0))}${m.unit ?? ""}`}</span>
          <span className="shrink-0 tabular-nums text-muted-foreground" title={m.change_days ? `${m.change_days}일 전 대비` : undefined}>
            {m.change_3m == null ? "변화 계산 불가(이력 짧음)" : `${m.change_3m >= 0 ? "+" : ""}${m.unit === "%" ? `${formatLevel(m.change_3m)}%p` : `${formatNumber(Math.round(m.change_3m))}bp`} (${m.change_days}일)`}
          </span>
          {m.state && <Badge variant="outline" className={cn("shrink-0 px-1 text-[10px]", tone(m.state))}>{m.state}</Badge>}
        </>}
      </li>)}
    </ul>
  </div>
}

/** P×Q 분해 — 금액 변화가 단가·구성에서 왔나, 물량에서 왔나(한국 수출, kg 기준) */
function PxqList({ pxq }: { pxq: VcPxq[] }) {
  const pct = (v: number) => formatPercent(v)
  return <div className="mt-3">
    <p className="text-caption font-medium text-muted-foreground" title="3개월 합 기준 YoY. 칩은 kg이 물량을 대표하지 못해 단가에 제품 구성 변화가 섞인다">P×Q 분해 — 한국 수출(3개월 YoY)</p>
    <ul className="divide-y text-caption">
      {pxq.map(d => <li key={d.hs} className="space-y-0.5 py-1">
        <div className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate" title={d.hs}>{d.item}</span>
          <Badge variant="outline" className="shrink-0 px-1 text-[10px]">{d.verdict}</Badge>
        </div>
        <div className="flex flex-wrap gap-x-3 tabular-nums text-muted-foreground">
          <span>금액 {pct(d.value_yoy)}</span><span>단가·구성 {pct(d.price_yoy)}</span><span>물량 {pct(d.qty_yoy)}</span>
          {d.price_share != null && <span>단가 기여 {d.price_share}%</span>}<span className="ml-auto">{d.period}</span>
        </div>
      </li>)}
    </ul>
  </div>
}

/** 돈의 흐름 카드 — 흐름 크기 막대, 스포트라이트 가설(반증 조건 포함), 시장이 의심하는 칸, 식는 칸 */
function FlowCard({ data, onSelect }: { data: FlowResponse; onSelect: (k: string) => void }) {
  const max = Math.max(...data.flows.map(f => f.increment_change_usd ?? 0), 1)
  const Row = ({ r, tone }: { r: FlowRow; tone: string }) => <Button variant="ghost" onClick={() => onSelect(r.key)}
    className="block h-auto w-full whitespace-normal rounded-md px-2 py-1.5 text-left text-sm font-normal">
    <span className={cn("font-medium", tone)}>{r.name}</span>
    {r.kr.length > 0 && <span className="ml-1.5 text-caption text-muted-foreground">{r.kr.slice(0, 4).join("·")}{r.kr.length > 4 ? " 외" : ""}</span>}
    {r.why && <span className="block text-caption text-muted-foreground">{r.why}</span>}
    {r.falsifier && <span className="block text-caption text-muted-foreground">반증: {r.falsifier}</span>}
  </Button>
  return <Card>
    <CardHeader className="pb-2">
      <CardTitle className="text-card-title">돈의 흐름</CardTitle>
      <p className="text-caption text-muted-foreground">
        흐름 = 최근 3개월(분기 칸은 최신 분기, 회사채는 최근 4분기 합) 전년 대비 증가 금액(대만달러는 고정 {data.twd_usd}로 환산), 막대 = 그 증가 금액이 직전 창(3개월·한 분기 전)보다 늘어난 만큼(금액 기준이라 큰 칸이 위에 옵니다 — 크기와 무관한 비교는 칸 상태 σ). 가속 = 성장률 변화가 그 칸의 평소 변동의 1배(1σ) 이상. 아래 목록은 예측이 아니라 반증 조건이 붙은 가설입니다 —
        칸 사이 선행 시차는 대부분 통계적으로 확인되지 않았습니다. 시장 반응 = 칸 한국 종목 3개월 수익률(중앙값 {formatPercent(data.median_kr_return_3m)}), 관심 = 최근 30일 문서 수.
      </p>
    </CardHeader>
    <CardContent><BoundedArea size="lg"><div className="grid gap-5 lg:grid-cols-2">
      <div>
        <p className="mb-1.5 text-caption font-medium text-muted-foreground">흐름이 빨라지는 칸 — 증가 금액이 직전 창보다 늘어난 만큼</p>
        <ul className="space-y-1">
          {data.flows.map(f => <li key={f.key}>
            <Button variant="ghost" onClick={() => onSelect(f.key)} className="grid h-auto w-full grid-cols-[120px_minmax(0,1fr)_72px] items-center gap-2 px-1 py-1 text-left text-caption font-normal"
              title={`증가 금액 +${formatUsd(f.increment_usd ?? 0)} (직전 창 +${formatUsd(f.increment_prev_usd ?? 0)}) · ${f.period}`}>
              <span className="truncate font-medium">{f.name}</span>
              <span className="h-2 rounded-full bg-chart-blue/70" style={{ width: `${Math.max(4, ((f.increment_change_usd ?? 0) / max) * 100)}%` }} />
              <span className="text-right tabular-nums">+{formatUsd(f.increment_change_usd ?? 0)}</span>
            </Button>
          </li>)}
        </ul>
      </div>
      <div className="space-y-3">
        <div><p className="text-caption font-medium text-muted-foreground">다음 스포트라이트 가설 — 흐름은 가속, 시장은 아직 조용</p>
          {data.spotlight.length ? data.spotlight.map(r => <Row key={r.key} r={r} tone="text-up-ink" />) : <p className="px-2 text-caption text-muted-foreground">해당 칸이 없습니다.</p>}</div>
        <div><p className="text-caption font-medium text-muted-foreground">흐름은 가속인데 시장이 의심하는 칸 — 이유 확인 대상</p>
          {data.doubted.length ? data.doubted.map(r => <Row key={r.key} r={{ ...r, falsifier: null }} tone="" />) : <p className="px-2 text-caption text-muted-foreground">해당 칸이 없습니다.</p>}</div>
        <div><p className="text-caption font-medium text-muted-foreground">식는 칸 — 흐름은 둔화, 관심·주가는 아직 높음</p>
          {data.fading.length ? data.fading.map(r => <Row key={r.key} r={r} tone="text-down-ink" />) : <p className="px-2 text-caption text-muted-foreground">해당 칸이 없습니다.</p>}</div>
        {!!data.needs_check?.length && <div><p className="text-caption font-medium text-muted-foreground">확인 필요 — 업계 수출은 가속이지만 대리 관측이고 종목 공시가 받쳐 주지 않음</p>
          {data.needs_check.map(r => <Row key={r.key} r={r} tone="" />)}</div>}
      </div>
    </div></BoundedArea></CardContent>
  </Card>
}


const MAP_INFO = "행 = 단계(자본 조달 → 최종 수요 → 완제품 → 부품 → 칩 → 생산 → 장비 → 소재), 열 = 수요 갈래. 칸 = 이름 · 이번 달 상태 · 3개월 전년 대비. 상태는 성장률 변화가 그 칸 평소 변동의 ±1σ 이상이면 가속·둔화(이력이 짧은 칸은 ±10%p). 관측 원천: 대만 월매출 · 미국 분기 실적 · 한국 수출 HS(한국 장비·소재 칸은 업계 전체 수출로 보는 대리 관측) · 중국 세관·일본 무역통계. 회사 전체 매출이라 비 AI 사업이 섞입니다. 칸을 누르면 연결된 앞뒤 칸이 표시되고 상세가 열립니다."
const STATES = ["가속", "유지", "둔화", "전환↑", "전환↓"] as const
const CHIP_TONE: Record<string, string> = {
  "가속": "bg-up/10 text-up-ink", "유지": "bg-muted text-muted-foreground", "둔화": "bg-down/10 text-down-ink",
  "전환↑": "bg-chart-green/15 text-chart-green", "전환↓": "bg-chart-orange/15 text-chart-orange",
}

/** 요약 줄 — 관측 노드 수(수요 칸 제외) · 가속 · 유지 · 둔화와 전환↓ */
function vcSummary(vc: ValueChainResponse): SummaryCell[] {
  const n = (st: string) => vc.nodes.filter(x => x.state === st).length
  const turnUp = n("전환↑")
  return [
    { label: "관측 노드", value: formatNumber(vc.nodes.filter(x => x.source).length), sub: vc.as_of ?? "-" },
    { label: "가속", value: formatNumber(n("가속")), className: "text-up-ink", sub: turnUp ? `전환↑ ${turnUp}` : undefined },
    { label: "유지", value: formatNumber(n("유지")) },
    { label: "둔화·전환↓", value: formatNumber(n("둔화") + n("전환↓")), className: "text-down-ink" },
  ]
}

function StateLegend() {
  return <div className="flex flex-wrap items-center gap-1.5 text-xs">
    <span className="text-muted-foreground">상태</span>
    <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon-xs" aria-label="상태 설명" className="text-muted-foreground/70"><Info className="size-3.5" /></Button></TooltipTrigger>
      <TooltipContent className="max-w-[280px] text-xs">3개월 전년 대비 성장률이 3개월 전보다 평소 변동의 1배 넘게 빨라지면 가속, 느려지면 둔화, 방향이 바뀌면 전환입니다.</TooltipContent></Tooltip>
    {STATES.map(st => <span key={st} className={cn("px-1.5 py-0.5 font-medium", CHIP_TONE[st])}>{st}</span>)}
  </div>
}

/** 지도 격자 — 행 = 단계(tiers), 열 = 수요 갈래(lanes). 고른 칸은 진한 테두리, 이어진 앞뒤 칸은 얇은 테두리, 나머지는 흐리게 */
function VcGrid({ vc, selected, onSelect }: { vc: ValueChainResponse; selected: string | null; onSelect: (k: string) => void }) {
  const near = new Set(selected ? vc.edges.filter(e => e.from === selected || e.to === selected).flatMap(e => [e.from, e.to]) : [])
  const items = [...vc.demands.map(d => ({ key: d.key, name: d.name, state: d.state, yoy: d.yoy_3m, observed: !!d.obs_label })),
    ...vc.nodes.map(n => ({ key: n.key, name: n.name, state: n.state, yoy: n.yoy_3m, observed: !!n.source }))]
  const cell = (tier: string, lane: string) => items.filter(i => vc.layout[i.key]?.tier === tier && vc.layout[i.key]?.lane === lane)
  const cols = `6.5rem repeat(${vc.lanes.length}, minmax(8.5rem, 1fr))`
  return <div className="overflow-x-auto" data-vc-grid>
    <div className="grid min-w-[49rem] text-xs" style={{ gridTemplateColumns: cols }}>
      <div />
      {vc.lanes.map(l => <div key={l.key} className="border-b px-2 pb-1.5 font-semibold text-muted-foreground">{l.label}</div>)}
      {vc.tiers.map(t => <div key={t.key} className="contents">
        <div className="border-b py-2 pr-2 text-muted-foreground">{t.label}</div>
        {vc.lanes.map(l => <div key={l.key} className="space-y-1.5 border-b border-l p-1.5">
          {cell(t.key, l.key).map(i => {
            const on = i.key === selected, linked = near.has(i.key)
            return <Button key={i.key} variant="ghost" onClick={() => onSelect(i.key)} aria-pressed={on} data-vc-node={i.key}
              className={cn("block h-auto w-full whitespace-normal rounded-md border px-2 py-1.5 text-left text-xs font-normal",
                i.state ? CHIP_TONE[i.state] : "bg-muted/40 text-muted-foreground", !i.observed && "border-dashed",
                on ? "border-2 border-foreground" : linked ? "border-foreground/50" : "border-transparent",
                selected && !on && !linked && "opacity-35")}>
              <span className="block truncate font-medium text-foreground">{i.name}</span>
              <span className="block text-[10.5px]">{i.observed ? `${i.state ?? "-"} · ${formatPercent(i.yoy)}` : "관측 없음"}</span>
            </Button>
          })}
        </div>)}
      </div>)}
    </div>
  </div>
}

/** 노드 상세 패널 — 옛 NodePanel·DemandPanel + 시장 기대. ×나 같은 칸을 다시 누르면 닫힌다 */
function DetailPanel({ vc, node, demand, onSelect, exp, expAsOf, compact, bare }: {
  vc: ValueChainResponse; node?: VcNode; demand?: VcDemand; onSelect: (k: string | null) => void
  exp?: ExpNode; expAsOf: string | null; compact?: boolean; bare?: boolean
}) {
  if (!node && !demand) return null
  const body = <div className="space-y-4">
    {demand ? <DemandPanel demand={demand} edges={vc.edges} nodes={vc.nodes} onSelect={onSelect} compact={compact} />
      : <NodePanel node={node} edges={vc.edges} nodes={vc.nodes} demands={vc.demands} onSelect={onSelect} compact={compact} />}
    {expAsOf && <ExpectationPanel exp={exp} asOf={expAsOf} />}
  </div>
  if (bare) return body
  return <div className="relative border p-3" data-vc-panel>
    <Button variant="ghost" size="icon-xs" className="absolute right-2 top-2 text-muted-foreground" aria-label="상세 닫기" onClick={() => onSelect(null)}><X className="size-3.5" /></Button>
    {body}
  </div>
}

function DemandTable({ demands, onSelect }: { demands: VcDemand[]; onSelect: (k: string) => void }) {
  return <Table className="text-[13px]">
    <TableHeader><TableRow>
      <TableHead className="h-8 pl-3 text-[11px]">수요</TableHead><TableHead className="h-8 text-[11px] max-md:hidden">무엇으로 보나</TableHead>
      <TableHead className="h-8 text-right text-[11px]">3개월 전년 대비</TableHead><TableHead className="h-8 pr-3 text-right text-[11px]">상태</TableHead>
    </TableRow></TableHeader>
    <TableBody>{demands.map(d => <TableRow key={d.key} className="cursor-pointer" onClick={() => onSelect(d.key)}>
      <TableCell className="py-2 pl-3 font-medium">{d.name}<span className="block text-[11px] font-normal text-muted-foreground md:hidden">{d.obs_label ?? "-"}</span></TableCell>
      <TableCell className="max-w-md whitespace-normal py-2 text-muted-foreground max-md:hidden">{d.obs_label ?? "-"}</TableCell>
      <TableCell className={cn("py-2 text-right font-mono tabular-nums", d.yoy_3m == null ? "text-muted-foreground" : d.yoy_3m > 0 ? "text-up-ink" : "text-down-ink")}>{formatPercent(d.yoy_3m)}</TableCell>
      <TableCell className="py-2 pr-3 text-right">{d.state ? <span className={cn("px-1.5 py-0.5 text-xs", CHIP_TONE[d.state])}>{d.state}</span> : <span className="text-muted-foreground">-</span>}</TableCell>
    </TableRow>)}</TableBody>
  </Table>
}
