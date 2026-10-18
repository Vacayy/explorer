import { useMemo } from "react"
import { Layer, Rectangle, ResponsiveContainer, Sankey, Tooltip } from "recharts"
import { EmptyState } from "@/components/shared/ErrorState"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { formatUsd } from "@/utils/format"
import type { EdgeFlow, ValueChainResponse } from "@/types"

/**
 * 공급 지도의 금액 규모(docs/specs/value-chain.md §14) — 칸 규모 → 중력 원 지름(로그), 선별 추정 증가액 → 선 굵기(제곱근).
 * 선 굵기는 실제 거래액이 아니라 공급 칸 증가액을 사는 칸 규모 비례로 나눈 추정이다.
 */

export const SANKEY_TOP = 30
export const MAG_HINT = "선 굵기는 실제 거래액이 아닙니다 — 공급 칸의 전년 대비 증가액을, 그 칸이 파는 칸들에 사는 칸 규모 비례로 나눈 추정입니다."

/** 로그 스케일 지름(px) — 회사 전체 매출과 수출 품목 하나는 수백 배 차이라 선형이면 작은 칸이 사라진다 */
export function gravity(level: number | null | undefined, min: number, max: number, lo = 8, hi = 30): number | null {
  if (!level || level <= 0 || !(max > min)) return level ? (lo + hi) / 2 : null
  const t = (Math.log(level) - Math.log(min)) / (Math.log(max) - Math.log(min))
  return lo + Math.max(0, Math.min(1, t)) * (hi - lo)
}

/** 제곱근 스케일 선 굵기(px) — 증가액이 0 이하이거나 모르면 가는 기본선 */
export function streamWidth(flow: number | null | undefined, max: number, lo = 1, hi = 14): number {
  if (!flow || flow <= 0 || max <= 0) return lo
  return lo + Math.sqrt(flow / max) * (hi - lo)
}

export type SankeyLane = "all" | "ai" | "pc" | "mobile" | "china"
const LANES: { key: SankeyLane; label: string }[] = [
  { key: "all", label: "전체" }, { key: "ai", label: "AI 데이터센터" }, { key: "pc", label: "PC" }, { key: "mobile", label: "스마트폰" }, { key: "china", label: "중국" },
]

type SNode = { name: string; key: string; level: number | null }
type SLink = { source: number; target: number; value: number; from: string; to: string }

/** 생키 데이터 — 돈은 사는 쪽(저장 엣지의 to) → 파는 쪽(from). 레인 필터 후 추정 증가액 상위 N, 순환을 만드는 연결은 뺀다 */
export function buildSankey(vc: ValueChainResponse, flows: EdgeFlow[], level: Record<string, number | null>, lane: SankeyLane, top = SANKEY_TOP) {
  const name = (k: string) => vc.nodes.find(n => n.key === k)?.name ?? vc.demands.find(d => d.key === k)?.name ?? k
  const inLane = (k: string) => lane === "all" || vc.layout[k]?.lane === lane
  const cand = flows.filter(f => inLane(f.from) || inLane(f.to))
  const positive = cand.filter(f => (f.flow_usd ?? 0) > 0).sort((a, b) => b.flow_usd! - a.flow_usd!)
  const picked = positive.slice(0, top)
  const adj: Record<string, string[]> = {}
  const reach = (a: string, b: string): boolean => {                 // a에서 b로 갈 수 있나(순환 검사)
    const seen = new Set<string>(); const st = [a]
    while (st.length) { const x = st.pop()!; if (x === b) return true; if (seen.has(x)) continue; seen.add(x); st.push(...(adj[x] ?? [])) }
    return false
  }
  const nodes: SNode[] = []
  const idx: Record<string, number> = {}
  const id = (k: string) => (idx[k] ??= nodes.push({ name: name(k), key: k, level: level[k] ?? null }) - 1)
  const links: SLink[] = []
  for (const f of picked) {
    const src = f.to, dst = f.from                                    // 돈: 사는 칸 → 파는 칸
    if (reach(dst, src)) continue
    ;(adj[src] ??= []).push(dst)
    links.push({ source: id(src), target: id(dst), value: f.flow_usd!, from: src, to: dst })
  }
  return { nodes, links, hidden: positive.length - links.length, nonPositive: cand.length - positive.length }
}

function SankeyNode(props: { x: number; y: number; width: number; height: number; index: number; payload: SNode & { value: number } }) {
  const { x, y, width, height, payload } = props
  // 라벨은 항상 막대 오른쪽 — 맨 오른쪽 열은 오른쪽 여백(margin.right)에 들어간다
  return <Layer>
    <Rectangle x={x} y={y} width={width} height={Math.max(height, 2)} fill="var(--color-chart-blue)" fillOpacity={0.85} />
    <text x={x + width + 6} y={y + height / 2} textAnchor="start" dominantBaseline="middle" fontSize={11} fill="var(--foreground)"
      paintOrder="stroke" stroke="var(--background)" strokeWidth={3} strokeLinejoin="round">
      {payload.name}
      <tspan fill="var(--muted-foreground)">{payload.level ? ` · ${formatUsd(payload.level)}` : ""}</tspan>
    </text>
  </Layer>
}

/** 툴팁 — 띠(연결)는 우리가 실어 둔 from·to로 구분한다(Recharts의 source 인덱스 0은 거짓으로 읽혀 판정에 못 쓴다) */
function SankeyTip({ active, payload, names }: {
  active?: boolean; names: Record<string, string>
  payload?: { payload: { from?: string; to?: string; value?: number; name?: string; level?: number | null; payload?: { from?: string; to?: string; value?: number } } }[]
}) {
  if (!active || !payload?.length) return null
  const raw = payload[0].payload
  const link = raw.from && raw.to ? raw : raw.payload?.from && raw.payload?.to ? raw.payload : null
  return <div className="max-w-[280px] rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md">
    {link
      ? <><div className="font-medium">{names[link.from!] ?? link.from} → {names[link.to!] ?? link.to}</div>
        <div className="tabular-nums">추정 증가액 +{formatUsd(link.value ?? 0)}</div>
        <div className="mt-1 text-muted-foreground">{MAG_HINT}</div></>
      : <><div className="font-medium">{raw.name}</div><div className="tabular-nums">규모 {raw.level ? formatUsd(raw.level) : "-"}</div></>}
  </div>
}

export function ValueChainSankey({ vc, flows, level, lane, onLane, onSelect }: {
  vc: ValueChainResponse; flows: EdgeFlow[]; level: Record<string, number | null>; lane: SankeyLane
  onLane: (l: SankeyLane) => void; onSelect: (k: string) => void
}) {
  const data = useMemo(() => buildSankey(vc, flows, level, lane), [vc, flows, level, lane])
  return <div className="space-y-2">
    <div className="flex flex-wrap items-center gap-2">
      <ToggleGroup type="single" size="sm" variant="outline" value={lane} onValueChange={v => v && onLane(v as SankeyLane)} aria-label="레인">
        {LANES.map(l => <ToggleGroupItem key={l.key} value={l.key} className="px-3 text-xs">{l.label}</ToggleGroupItem>)}
      </ToggleGroup>
      <span className="text-caption text-muted-foreground">
        띠 두께 = 추정 증가액 상위 {data.links.length}개{data.hidden > 0 ? ` · 그리지 않은 연결 ${data.hidden}개` : ""}{data.nonPositive > 0 ? ` · 증가액 0 이하 ${data.nonPositive}개 제외` : ""}
      </span>
    </div>
    {!data.links.length ? <EmptyState message="그릴 증가액 연결이 없습니다 — 다른 레인을 골라 보세요." />
      : <div className="h-[640px] rounded-lg border p-2">
        <ResponsiveContainer width="100%" height="100%">
          <Sankey data={data} nodePadding={14} nodeWidth={10} iterations={64} margin={{ top: 8, right: 220, bottom: 8, left: 8 }}
            link={{ stroke: "var(--color-chart-blue)", strokeOpacity: 0.28 }}
            node={(p: unknown) => <SankeyNode {...(p as Parameters<typeof SankeyNode>[0])} />}
            onClick={(e: unknown) => { const k = (e as { payload?: SNode })?.payload?.key; if (k) onSelect(k) }}>
            <Tooltip content={<SankeyTip names={Object.fromEntries(data.nodes.map(n => [n.key, n.name]))} />} />
          </Sankey>
        </ResponsiveContainer>
      </div>}
  </div>
}
