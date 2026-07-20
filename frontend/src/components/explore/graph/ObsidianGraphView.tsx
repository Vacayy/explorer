import { useCallback, useMemo, useRef, useState } from "react"
import ForceGraph2D from "react-force-graph-2d"
import { useElementSize } from "./useElementSize"
import { NODE_COLOR, NODE_COLOR_FALLBACK, NODE_LABEL, nodeRadius, type WNode, type WEdge } from "./types"

/**
 * 옵시디언式 2D 포스 그래프 (react-force-graph-2d = HTML5 Canvas + d3-force).
 * 옵시디언 시그니처: 차수 비례 노드 크기 · hover 시 이웃 강조+나머지 디밍.
 * 가독성 개선: 작은 그래프(초점/백본)에선 라벨 상시 노출 · 방향 파티클로 인과 흐름 직관 ·
 * 링크 곡선·노드 테두리 · 타입 색 범례.
 */
const LABEL_COLOR = "#64748b"       // 라이트·다크 공통 중립색 (canvas는 CSS 변수 못 씀)
const LABEL_ACTIVE = "#334155"
const RING_COLOR = "rgba(100,116,139,0.45)"

const endId = (x: unknown): number =>
  typeof x === "object" && x !== null ? (x as WNode).id : (x as number)

export default function ObsidianGraphView({
  nodes, edges, onNodeSelect,
}: {
  nodes: WNode[]; edges: WEdge[]; onNodeSelect: (n: WNode) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const { width, height } = useElementSize(ref)
  const [hoverId, setHoverId] = useState<number | null>(null)
  // 노드 수가 적으면(초점/백본) 라벨을 상시 노출 — 굳이 hover 안 해도 지도가 읽힌다
  const alwaysLabel = nodes.length <= 40

  const graphData = useMemo(() => ({
    nodes: nodes.map((n) => ({ ...n })),
    links: edges.map((e) => ({ ...e, source: e.from_id, target: e.to_id })),
  }), [nodes, edges])

  const neighbors = useMemo(() => {
    const m = new Map<number, Set<number>>()
    edges.forEach((e) => {
      ;(m.get(e.from_id) ?? m.set(e.from_id, new Set()).get(e.from_id)!).add(e.to_id)
      ;(m.get(e.to_id) ?? m.set(e.to_id, new Set()).get(e.to_id)!).add(e.from_id)
    })
    return m
  }, [edges])

  const presentTypes = useMemo(
    () => [...new Set(nodes.map((n) => n.type))].filter((t) => NODE_COLOR[t]), [nodes])

  const nodeActive = useCallback((id: number) => {
    if (hoverId == null) return true
    return id === hoverId || (neighbors.get(hoverId)?.has(id) ?? false)
  }, [hoverId, neighbors])

  const linkActive = useCallback((l: unknown) => {
    if (hoverId == null) return true
    const o = l as { source: unknown; target: unknown }
    return endId(o.source) === hoverId || endId(o.target) === hoverId
  }, [hoverId])

  return (
    <div ref={ref} className="relative h-full w-full">
      {width > 0 && (
        <ForceGraph2D
          width={width}
          height={height}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          cooldownTicks={120}
          minZoom={0.1}
          maxZoom={8}
          linkCurvature={0.12}
          onNodeHover={(n) => setHoverId(n ? (n as WNode).id : null)}
          onNodeClick={(n) => onNodeSelect(n as WNode)}
          linkColor={(l) => {
            const e = l as unknown as WEdge
            if (!linkActive(l)) return "rgba(148,163,184,0.05)"
            if (e.contested) return "rgba(239,68,68,0.8)"
            if (e.flywheel) return "rgba(245,158,11,0.85)"
            return "rgba(148,163,184,0.4)"
          }}
          linkWidth={(l) => ((l as unknown as WEdge).corroborated_by >= 2 ? 2.2 : 1)}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkDirectionalParticles={(l) => {
            const e = l as unknown as WEdge
            if (!linkActive(l)) return 0
            return e.flywheel || e.corroborated_by >= 2 ? 3 : 2   // 파티클이 원인→결과로 흐르며 방향을 보여줌
          }}
          linkDirectionalParticleWidth={2}
          linkDirectionalParticleColor={(l) => {
            const e = l as unknown as WEdge
            return e.contested ? "#ef4444" : e.flywheel ? "#f59e0b" : "#94a3b8"
          }}
          nodeCanvasObjectMode={() => "replace"}
          nodePointerAreaPaint={(node, color, ctx) => {
            const n = node as WNode & { x: number; y: number }
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(n.x, n.y, nodeRadius(n) + 3, 0, 2 * Math.PI)
            ctx.fill()
          }}
          nodeCanvasObject={(node, ctx, scale) => {
            const n = node as WNode & { x: number; y: number }
            const active = nodeActive(n.id)
            const isHover = n.id === hoverId
            const r = nodeRadius(n)
            ctx.globalAlpha = active ? 1 : 0.12
            // 노드 원 + 테두리(대비)
            ctx.beginPath()
            ctx.arc(n.x, n.y, r, 0, 2 * Math.PI)
            ctx.fillStyle = NODE_COLOR[n.type] ?? NODE_COLOR_FALLBACK
            ctx.fill()
            ctx.lineWidth = isHover ? 2 / scale : 0.7 / scale
            ctx.strokeStyle = isHover ? "#0071e3" : RING_COLOR
            ctx.stroke()
            // 라벨: 작은 그래프면 상시, 아니면 줌인·hover 시
            if (alwaysLabel || scale > 1.1 || (hoverId != null && active)) {
              const fontSize = Math.max(3, 11 / scale)
              ctx.font = `${isHover ? "600 " : ""}${fontSize}px sans-serif`
              ctx.textAlign = "center"
              ctx.textBaseline = "top"
              ctx.fillStyle = active ? (isHover ? LABEL_ACTIVE : LABEL_COLOR) : LABEL_COLOR
              ctx.fillText(n.name, n.x, n.y + r + 1.5)
            }
            ctx.globalAlpha = 1
          }}
        />
      )}
      {/* 타입 색 범례 */}
      {presentTypes.length > 0 && (
        <div className="absolute bottom-2 left-2 flex flex-wrap gap-x-2.5 gap-y-1 rounded-lg border bg-card/85 px-2.5 py-1.5 text-[10px] text-muted-foreground backdrop-blur">
          {presentTypes.map((t) => (
            <span key={t} className="inline-flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: NODE_COLOR[t] }} />
              {NODE_LABEL[t] ?? t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
