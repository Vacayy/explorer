/** 세계관 그래프 공유 타입·상수 — 구조(React Flow)·3D·옵시디언 PoC가 공유. */

export interface WNode {
  id: number; name: string; type: string
  in_degree: number; out_degree: number; cluster_id: number
  in_flywheel?: boolean
  pace_layer?: string | null   // event|flow|cycle|structure|regime — 노드 중력 (D-030)
}

export interface WEdge {
  from: string; from_id: number; from_type: string | null
  to: string; to_id: number; to_type: string | null
  rel: string; mechanism: string | null; orientation: string | null
  reference_period: string | null; confidence: number | null
  corroborated_by: number; contested: boolean; promoted_knowledge_id: number | null
  feedback_note?: string | null   // both_temporal 해소 근거 (D-029)
  flywheel?: boolean
}

export interface Worldview { nodes: WNode[]; edges: WEdge[] }

export const NODE_LABEL: Record<string, string> = {
  company: "기업", sector: "섹터", theme: "테마", person: "인물",
  macro: "매크로", policy: "정책", event: "사건",
}

// canvas/WebGL 렌더는 CSS 변수를 직접 못 써서 고정 팔레트 사용 (PoC — 라이트/다크 공통 무난).
export const NODE_COLOR: Record<string, string> = {
  company: "#3b82f6", sector: "#10b981", theme: "#a855f7", person: "#f59e0b",
  macro: "#ef4444", policy: "#6366f1", event: "#64748b",
}
export const NODE_COLOR_FALLBACK = "#94a3b8"

/** 노드 반지름 — 연결 차수(중요도)에 비례. */
export const nodeRadius = (n: WNode) => 3 + Math.sqrt(n.in_degree + n.out_degree) * 1.6
