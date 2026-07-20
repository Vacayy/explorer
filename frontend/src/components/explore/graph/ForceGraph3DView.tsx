import { useMemo, useRef } from "react"
import ForceGraph3D from "react-force-graph-3d"
import { useElementSize } from "./useElementSize"
import { NODE_COLOR, NODE_COLOR_FALLBACK, NODE_LABEL, nodeRadius, type WNode, type WEdge } from "./types"

/**
 * 3D 포스 그래프 PoC (react-force-graph-3d = ThreeJS/WebGL + d3-force-3d).
 * 회전·줌 가능한 3D 배치 — "재미있는" 탐험 뷰. 시간 그래디언트(좌→우)는 없음(구조 뷰가 담당).
 * 백엔드 무변경 — 세계관 데이터(nodes/edges) 그대로 소비.
 */
export default function ForceGraph3DView({
  nodes, edges, onNodeSelect,
}: {
  nodes: WNode[]; edges: WEdge[]; onNodeSelect: (n: WNode) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const { width, height } = useElementSize(ref)

  const graphData = useMemo(() => ({
    nodes: nodes.map((n) => ({ ...n })),
    links: edges.map((e) => ({ ...e, source: e.from_id, target: e.to_id })),
  }), [nodes, edges])

  return (
    <div ref={ref} className="h-full w-full">
      {width > 0 && (
        <ForceGraph3D
          width={width}
          height={height}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          nodeLabel={(n) => `${NODE_LABEL[(n as WNode).type] ?? (n as WNode).type} · ${(n as WNode).name}`}
          nodeColor={(n) => NODE_COLOR[(n as WNode).type] ?? NODE_COLOR_FALLBACK}
          nodeVal={(n) => nodeRadius(n as WNode)}
          nodeOpacity={0.9}
          nodeResolution={12}
          linkColor={(l) => {
            const e = l as unknown as WEdge
            return e.contested ? "#ef4444" : e.flywheel ? "#f59e0b" : "rgba(148,163,184,0.35)"
          }}
          linkWidth={(l) => ((l as unknown as WEdge).corroborated_by >= 2 ? 1.5 : 0.5)}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkDirectionalParticles={(l) => ((l as unknown as WEdge).flywheel ? 2 : 0)}
          linkDirectionalParticleWidth={1.5}
          onNodeClick={(n) => onNodeSelect(n as WNode)}
          enableNodeDrag={false}
        />
      )}
    </div>
  )
}
