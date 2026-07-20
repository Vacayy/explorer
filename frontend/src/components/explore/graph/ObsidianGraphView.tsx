import { useCallback, useMemo, useRef, useState } from "react"
import ForceGraph2D from "react-force-graph-2d"
import { useElementSize } from "./useElementSize"
import { NODE_COLOR, NODE_COLOR_FALLBACK, nodeRadius, type WNode, type WEdge } from "./types"

/**
 * 옵시디언式 2D 포스 그래프 PoC (react-force-graph-2d = HTML5 Canvas + d3-force).
 * 옵시디언 시그니처 재현: 차수 비례 노드 크기 · hover 시 이웃 하이라이트+나머지 디밍 ·
 * 줌인/hover 시 라벨 노출. (옵시디언 실물은 PixiJS/WebGL 엔진 — 여기선 느낌만 동일하게 구현)
 * 백엔드 무변경 — 세계관 데이터 그대로 소비.
 */
const LABEL_COLOR = "#64748b"   // 라이트·다크 공통 가독 중립색 (canvas는 CSS 변수 못 씀)

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

  const nodeActive = useCallback((id: number) => {
    if (hoverId == null) return true
    return id === hoverId || (neighbors.get(hoverId)?.has(id) ?? false)
  }, [hoverId, neighbors])

  return (
    <div ref={ref} className="h-full w-full">
      {width > 0 && (
        <ForceGraph2D
          width={width}
          height={height}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          cooldownTicks={120}
          onNodeHover={(n) => setHoverId(n ? (n as WNode).id : null)}
          onNodeClick={(n) => onNodeSelect(n as WNode)}
          linkColor={(l) => {
            const e = l as unknown as WEdge
            const active = hoverId == null || endId((l as { source: unknown }).source) === hoverId
              || endId((l as { target: unknown }).target) === hoverId
            if (!active) return "rgba(148,163,184,0.05)"
            if (e.contested) return "rgba(239,68,68,0.75)"
            if (e.flywheel) return "rgba(245,158,11,0.85)"
            return "rgba(148,163,184,0.35)"
          }}
          linkWidth={(l) => ((l as unknown as WEdge).corroborated_by >= 2 ? 2 : 1)}
          linkDirectionalArrowLength={2.5}
          linkDirectionalArrowRelPos={1}
          nodeCanvasObjectMode={() => "replace"}
          nodePointerAreaPaint={(node, color, ctx) => {
            const n = node as WNode & { x: number; y: number }
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(n.x, n.y, nodeRadius(n) + 2, 0, 2 * Math.PI)
            ctx.fill()
          }}
          nodeCanvasObject={(node, ctx, scale) => {
            const n = node as WNode & { x: number; y: number }
            const active = nodeActive(n.id)
            const r = nodeRadius(n)
            ctx.globalAlpha = active ? 1 : 0.15
            ctx.beginPath()
            ctx.arc(n.x, n.y, r, 0, 2 * Math.PI)
            ctx.fillStyle = NODE_COLOR[n.type] ?? NODE_COLOR_FALLBACK
            ctx.fill()
            // 라벨: 충분히 줌인했거나 hover 관련 노드일 때만 (클러터 감소)
            if (scale > 1.4 || (hoverId != null && active)) {
              const fontSize = Math.max(2.5, 11 / scale)
              ctx.font = `${fontSize}px sans-serif`
              ctx.textAlign = "center"
              ctx.textBaseline = "top"
              ctx.fillStyle = LABEL_COLOR
              ctx.fillText(n.name, n.x, n.y + r + 1)
            }
            ctx.globalAlpha = 1
          }}
        />
      )}
    </div>
  )
}
