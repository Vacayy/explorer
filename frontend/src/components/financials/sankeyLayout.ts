// Sankey 레이아웃 — 순수 함수. 열(column) 좌표와 띠(link) 경로를 계산한다.
//
// 규칙:
// - 열마다 세로 쌓기: 매출/keep/inflow 위에서 아래, cost 아래에서 위
// - 모든 노드의 높이·띠 높이는 **한 스케일**(픽셀/금액). 그래서 열 합계가 다르면 열 총 높이도 다르다(사실 그대로)
// - 노드 폭 10px, 라벨은 노드 바깥(SVG에서 그린다)
// - 띠는 cubic Bezier. 노드 좌우에서 쓰는 Y 오프셋을 추적해 겹치지 않게 분배
//
// 음수 흐름은 백엔드가 이미 걸러낸다. 여기서는 양수만 들어온다 가정.

import type { FlowLink, FlowNode } from "@/types"

export interface LaidOutNode extends FlowNode {
  x: number; y: number; h: number
}
export interface LaidOutLink extends FlowLink {
  path: string
  sx: number; sy0: number; sy1: number
  tx: number; ty0: number; ty1: number
}
export interface SankeyLayout {
  nodes: LaidOutNode[]
  links: LaidOutLink[]
  nodeWidth: number
  width: number
  height: number
}

export interface LayoutOptions {
  width: number
  height: number
  nodeWidth?: number
  nodeGapY?: number           // 같은 열 노드 간격
  padding?: number            // 위·아래 여백
}

export function layoutSankey(nodes: FlowNode[], links: FlowLink[], opt: LayoutOptions): SankeyLayout {
  const nodeWidth = opt.nodeWidth ?? 10
  const nodeGapY = opt.nodeGapY ?? 10
  const padding = opt.padding ?? 24
  const chartH = opt.height - padding * 2

  const colIds = Array.from(new Set(nodes.map(n => n.column))).sort((a, b) => a - b)
  const nCols = colIds.length
  const colGap = nCols > 1 ? (opt.width - nCols * nodeWidth) / (nCols - 1) : 0
  const xOf = (col: number) => colIds.indexOf(col) * (nodeWidth + colGap)

  const byCol = new Map<number, FlowNode[]>()
  for (const n of nodes) {
    if (!byCol.has(n.column)) byCol.set(n.column, [])
    byCol.get(n.column)!.push(n)
  }

  // 스케일: 가장 '세로로 쌓이는' 열이 chartH를 거의 채우도록
  const colTotal = (c: number) => (byCol.get(c) ?? []).reduce((s, n) => s + n.value, 0)
  const maxTotal = Math.max(...colIds.map(colTotal), 1)
  const scale = (chartH - nodeGapY * 2) / maxTotal

  const placed = new Map<string, LaidOutNode>()
  for (const col of colIds) {
    const colNodes = byCol.get(col) ?? []
    // keep/revenue/inflow 위, cost 아래 (inflow는 특별 — 아래에서 들어오지만 노드 자체는 위 스택에 둔다)
    const upper = colNodes.filter(n => n.kind === 'revenue' || n.kind === 'keep')
    const inflow = colNodes.filter(n => n.kind === 'inflow')
    const lower = colNodes.filter(n => n.kind === 'cost')
    const x = xOf(col)
    let y = padding
    for (const n of upper) {
      const h = Math.max(2, n.value * scale)
      placed.set(n.id, { ...n, x, y, h })
      y += h + nodeGapY
    }
    let yb = opt.height - padding
    for (const n of lower) {
      const h = Math.max(2, n.value * scale)
      yb -= h
      placed.set(n.id, { ...n, x, y: yb, h })
      yb -= nodeGapY
    }
    // inflow는 lower(cost) 바로 위에 — 아래쪽 공간에서 keep 노드로 띠가 올라간다
    for (const n of inflow) {
      const h = Math.max(2, n.value * scale)
      yb -= h
      placed.set(n.id, { ...n, x, y: yb, h })
      yb -= nodeGapY
    }
  }

  // 링크 배치 — 노드 좌우 오프셋을 추적해 띠를 겹치지 않게 분배
  const rightUsed = new Map<string, number>()
  const leftUsed = new Map<string, number>()
  // 소스 Y 오름차순으로 돌려 띠가 자연스레 위→아래 분포하게
  const sortedLinks = [...links].sort((a, b) => {
    const sa = placed.get(a.source)?.y ?? 0
    const sb = placed.get(b.source)?.y ?? 0
    if (sa !== sb) return sa - sb
    const ta = placed.get(a.target)?.y ?? 0
    const tb = placed.get(b.target)?.y ?? 0
    return ta - tb
  })

  const laidLinks: LaidOutLink[] = []
  for (const l of sortedLinks) {
    const s = placed.get(l.source)
    const t = placed.get(l.target)
    if (!s || !t) continue
    const lh = l.value * scale
    const sU = rightUsed.get(l.source) ?? 0
    const tU = leftUsed.get(l.target) ?? 0
    const sx = s.x + nodeWidth
    const sy0 = s.y + sU
    const sy1 = sy0 + lh
    const tx = t.x
    const ty0 = t.y + tU
    const ty1 = ty0 + lh
    rightUsed.set(l.source, sU + lh)
    leftUsed.set(l.target, tU + lh)
    const cx = (sx + tx) / 2
    const path =
      `M${sx},${sy0} C${cx},${sy0} ${cx},${ty0} ${tx},${ty0} ` +
      `L${tx},${ty1} C${cx},${ty1} ${cx},${sy1} ${sx},${sy1} Z`
    laidLinks.push({ ...l, sx, sy0, sy1, tx, ty0, ty1, path })
  }

  return {
    nodes: Array.from(placed.values()),
    links: laidLinks,
    nodeWidth, width: opt.width, height: opt.height,
  }
}
