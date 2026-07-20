import { useCallback, useMemo, useRef, useState } from "react"
import ForceGraph2D from "react-force-graph-2d"
import { useElementSize } from "./useElementSize"
import { NODE_COLOR, NODE_COLOR_FALLBACK, NODE_LABEL, nodeRadius, type WNode, type WEdge } from "./types"

/**
 * 옵시디언式 2D 포스 그래프 (react-force-graph-2d = HTML5 Canvas + d3-force).
 * 옵시디언 시그니처: 차수 비례 노드 크기 · hover 시 이웃 강조+나머지 디밍.
 * 가독성: 작은 그래프(초점/백본)면 라벨 상시 · 라벨 배경 pill로 대비 · 방향 파티클로 인과 흐름 ·
 * 링크 곡선·노드 테두리 · 초점 노드 강조 · 타입 색 범례 · 다크모드 대응.
 */
const endId = (x: unknown): number =>
  typeof x === "object" && x !== null ? (x as WNode).id : (x as number)

export default function ObsidianGraphView({
  nodes, edges, onNodeSelect, isDark = false, focusId = null,
}: {
  nodes: WNode[]; edges: WEdge[]; onNodeSelect: (n: WNode) => void
  isDark?: boolean; focusId?: number | null
}) {
  const ref = useRef<HTMLDivElement>(null)
  const { width, height } = useElementSize(ref)
  const [hoverId, setHoverId] = useState<number | null>(null)
  const alwaysLabel = nodes.length <= 40   // 초점/백본이면 hover 없이도 지도가 읽히게

  // 다크모드 대응 색 (canvas는 CSS 변수 못 씀)
  const C = isDark
    ? { label: "#e2e8f0", labelDim: "#64748b", bg: "rgba(2,6,23,0.62)", ring: "rgba(148,163,184,0.5)" }
    : { label: "#334155", labelDim: "#94a3b8", bg: "rgba(255,255,255,0.66)", ring: "rgba(100,116,139,0.45)" }

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
            if (!linkActive(l)) return isDark ? "rgba(148,163,184,0.07)" : "rgba(148,163,184,0.05)"
            if (e.contested) return "rgba(239,68,68,0.8)"
            if (e.flywheel) return "rgba(245,158,11,0.85)"
            return isDark ? "rgba(148,163,184,0.5)" : "rgba(100,116,139,0.4)"
          }}
          linkWidth={(l) => ((l as unknown as WEdge).corroborated_by >= 2 ? 2.2 : 1)}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkDirectionalParticles={(l) => {
            const e = l as unknown as WEdge
            if (!linkActive(l)) return 0
            return e.flywheel || e.corroborated_by >= 2 ? 3 : 2   // 원인→결과로 흐르며 방향을 보여줌
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
            const emphasized = n.id === hoverId || n.id === focusId   // hover 또는 초점 중심
            const r = nodeRadius(n)
            ctx.globalAlpha = active ? 1 : 0.12
            ctx.beginPath()
            ctx.arc(n.x, n.y, r, 0, 2 * Math.PI)
            ctx.fillStyle = NODE_COLOR[n.type] ?? NODE_COLOR_FALLBACK
            ctx.fill()
            ctx.lineWidth = (emphasized ? 2 : 0.7) / scale
            ctx.strokeStyle = emphasized ? "#0071e3" : C.ring
            ctx.stroke()
            // 라벨 (배경 pill로 대비 확보)
            if (alwaysLabel || scale > 1.1 || (hoverId != null && active)) {
              const fontSize = Math.max(3, 11 / scale)
              ctx.font = `${emphasized ? "600 " : ""}${fontSize}px sans-serif`
              ctx.textAlign = "center"
              ctx.textBaseline = "top"
              const ly = n.y + r + 1.5
              const tw = ctx.measureText(n.name).width
              const pad = 2 / scale
              ctx.fillStyle = C.bg
              ctx.fillRect(n.x - tw / 2 - pad, ly - pad / 2, tw + pad * 2, fontSize + pad)
              ctx.fillStyle = emphasized ? C.label : (active ? C.label : C.labelDim)
              ctx.fillText(n.name, n.x, ly)
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
