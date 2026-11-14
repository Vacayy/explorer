// 도시에 › 실적·사업 탭 머리 섹션 — 분기 손익 흐름(Sankey). ia-redesign §4.13.
// 백엔드가 raw 금액·YoY·QoQ·이익률·콜아웃까지 완성해 돌려주므로 프런트는 레이아웃·라벨·토글만 맡는다.
//
// 상태 전개: 로딩 Skeleton, 404(자료 없음) 작은 안내, 에러 재시도, 받으면 렌더.

import { useState } from "react"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { Button } from "@/components/ui/button"
import { useFinancialsCollect, useIncomeFlow, useIncomeFlowQuarters } from "@/hooks/useIncomeFlow"
import type { FlowNode, IncomeFlowResponse } from "@/types"
import { layoutSankey, type LaidOutNode, type LaidOutLink } from "./sankeyLayout"
import { LINK_OPACITY, NODE_STYLE, calloutLabel, fmtMoney, fmtQuarterLabel, fmtSubtitle, nodeSubText } from "./flowFormat"
import { cn } from "@/lib/utils"

const PERIOD_TABS = [{ value: 'q', label: '단일 분기' }, { value: 'ttm', label: '최근 4분기 합' }]
const CHART_H = 440
const CHART_MIN_W = 980

/** 도시에 › 실적·사업 › 분기 손익 흐름 섹션. code=stock_code(KR) 또는 ticker(US). */
export function IncomeFlow({ code, market }: { code: string; market: 'kr' | 'us' }) {
  const [period, setPeriod] = useState<'q' | 'ttm'>('q')
  const quartersQ = useIncomeFlowQuarters(code, market)
  const [selectedQ, setSelectedQ] = useState<string | null>(null)
  const effectiveQ = selectedQ ?? quartersQ.data?.quarters[0]?.q ?? null
  const flow = useIncomeFlow(code, market, effectiveQ, period)

  // 분기 토글: 최근 4개
  const qTabs = (quartersQ.data?.quarters ?? []).slice(0, 4).map(it => ({
    value: it.q, label: fmtQuarterLabel(it.q, market),
  }))

  return (
    <Card className="gap-0 py-0" aria-label="분기 손익 흐름">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
        <h2 className="text-section font-semibold">분기 손익 흐름</h2>
        {flow.data && <span className="text-caption text-muted-foreground">{fmtSubtitle(flow.data, market)}</span>}
        <span className="ml-auto" />
        {qTabs.length > 0 && (
          <SegmentTabs tabs={qTabs} value={effectiveQ ?? ''} onChange={setSelectedQ} />
        )}
        <SegmentTabs tabs={PERIOD_TABS} value={period} onChange={(v) => setPeriod(v as 'q' | 'ttm')} />
      </header>
      <div className="p-4 space-y-3">
        {flow.isPending ? (
          <Skeleton className="h-[320px] w-full" />
        ) : flow.isError || !flow.data ? (
          <ErrorOrEmpty code={code} market={market} isError={flow.isError} onRetry={() => void flow.refetch()} />
        ) : (
          <IncomeFlowBody d={flow.data} market={market} />
        )}
      </div>
    </Card>
  )
}

/** 자료 없음 · 404 — 국내는 "DART에서 받아오기" 트리거를 함께 보여준다 (사각지대 소형주 대응). */
function ErrorOrEmpty({ code, market, isError, onRetry }: { code: string; market: 'kr' | 'us'; isError: boolean; onRetry: () => void }) {
  const collect = useFinancialsCollect(code)
  if (market !== 'kr') {
    return isError
      ? <ErrorState message="분기 손익을 불러오지 못했습니다." onRetry={onRetry} />
      : <p className="py-4 text-sm text-muted-foreground">아직 분기 손익 자료가 없습니다 — 분기보고서가 공시되면 채워집니다.</p>
  }
  const msg = collect.isSuccess
    ? (collect.data && collect.data.periods_added > 0
        ? `DART에서 ${collect.data.periods_added}개 분기를 새로 받았습니다. 잠시 후 다시 그려집니다.`
        : "DART에 새로 들어온 분기가 없었습니다. 분기보고서 공시 시점이 아닐 수 있어요.")
    : isError ? "분기 손익을 불러오지 못했습니다." : "아직 분기 손익 자료가 없습니다 — DART에서 받아보세요."
  return (
    <div className="space-y-2.5">
      <ErrorState message={msg} onRetry={isError && !collect.isPending ? onRetry : undefined} />
      <div className="flex items-center gap-2 text-caption text-muted-foreground">
        <Button size="sm" variant="outline" className="h-[30px] gap-1.5 text-[12.5px]"
                disabled={collect.isPending}
                onClick={() => collect.mutate()}>
          {collect.isPending ? "DART에서 받는 중… (최대 40콜)" : "DART에서 분기 재무 받아오기"}
        </Button>
        {collect.isError && <span className="text-down-ink">수집 실패 — 다시 시도해 주세요</span>}
        {collect.data && collect.data.calls > 0 && !collect.isPending && (
          <span>DART {collect.data.calls}콜 · {collect.data.periods_added}분기 추가</span>
        )}
      </div>
    </div>
  )
}

function IncomeFlowBody({ d, market }: { d: IncomeFlowResponse; market: 'kr' | 'us' }) {
  return (
    <>
      {d.callout && (
        <div className="flex gap-2 rounded bg-hyp-tint/60 px-3 py-2 text-sm">
          <span className="rounded bg-hyp/15 px-2 py-0.5 text-xs font-medium text-hyp">{calloutLabel(d.callout)}</span>
          <span className="flex-1 leading-relaxed">{d.callout.text}</span>
        </div>
      )}
      <div className="overflow-x-auto overscroll-x-contain">
        <SankeySvg d={d} />
      </div>
      <Legend />
      <SourceLine d={d} market={market} />
    </>
  )
}

function SankeySvg({ d }: { d: IncomeFlowResponse }) {
  const W = CHART_MIN_W
  const H = CHART_H
  // 세그먼트는 col 0에 '매출' 노드로 들어가는 inflow. 백엔드는 세그먼트를 별도 필드로 돌려주므로 여기서 노드·링크로 변환
  const segNodes: FlowNode[] = d.segments.map(s => ({
    id: `seg_${s.name}`, label: s.name, value: s.value, column: 0, kind: 'revenue' as const,
    subs: { yoy: s.yoy, qoq: s.qoq, margin: null, margin_yoy_pp: null, margin_qoq_pp: null,
            share_of_revenue: s.share, effective_tax_rate: null, note: null },
  }))
  const segLinks: typeof d.links = d.segments.map(s => ({
    source: `seg_${s.name}`, target: 'revenue', value: s.value,
  }))
  const { nodes, links } = layoutSankey([...segNodes, ...d.nodes], [...segLinks, ...d.links], { width: W, height: H })
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="min-w-[980px] max-w-full" aria-label="분기 손익 흐름 다이어그램">
      <g>
        {links.map((l, i) => <LinkBand key={i} link={l} nodeKindById={byId(nodes)} />)}
      </g>
      <g>
        {nodes.map(n => <NodeBar key={n.id} n={n} unit={d.unit} />)}
      </g>
    </svg>
  )
}

function byId(nodes: LaidOutNode[]): Record<string, FlowNode['kind']> {
  const out: Record<string, FlowNode['kind']> = {}
  for (const n of nodes) out[n.id] = n.kind
  return out
}

function LinkBand({ link, nodeKindById }: { link: LaidOutLink; nodeKindById: Record<string, FlowNode['kind']> }) {
  // 띠 색: 소스 노드의 kind를 따라감(revenue 띠는 매출 색 톤 등). 비용은 조금 더 흐리게
  const srcKind = nodeKindById[link.source] ?? 'keep'
  const fill = NODE_STYLE[srcKind].fill
  const opacity = LINK_OPACITY[srcKind] * (link.estimated ? 0.5 : 1)
  return (
    <path
      d={link.path}
      fill={fill}
      opacity={opacity}
      stroke={link.estimated ? fill : 'none'}
      strokeDasharray={link.estimated ? '4 3' : undefined}
      strokeWidth={link.estimated ? 1 : 0}
    />
  )
}

function NodeBar({ n, unit }: { n: LaidOutNode; unit: 'KRW' | 'USD' }) {
  const style = NODE_STYLE[n.kind]
  const subs = nodeSubText(n)
  const labelLeft = n.column === 0
  const labelRight = n.column >= 5
  const labelX = labelLeft ? n.x - 8 : labelRight ? n.x + 18 : n.x + 18
  const labelAnchor: 'start' | 'end' = labelLeft ? 'end' : 'start'
  const labelY = n.y + Math.min(n.h, 26) / 2 + 4
  return (
    <g>
      <rect
        x={n.x} y={n.y} width={10} height={n.h}
        fill={style.fill} opacity={style.opacity}
        stroke={n.estimated ? style.fill : 'none'}
        strokeDasharray={n.estimated ? '4 3' : undefined}
        rx={2}
      />
      <text x={labelX} y={labelY} textAnchor={labelAnchor} className="fill-current text-ink"
            style={{ fontSize: 12, fontWeight: 600 }}>
        {n.label}
      </text>
      <text x={labelX} y={labelY + 18} textAnchor={labelAnchor} className="fill-current text-ink"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 17 }}>
        {fmtMoney(n.value, unit)}
      </text>
      {subs.slice(0, 3).map((s, i) => (
        <text key={i} x={labelX} y={labelY + 34 + i * 12}
              textAnchor={labelAnchor} className="fill-current text-ink-3"
              style={{ fontSize: 11 }}>
          {s}
        </text>
      ))}
    </g>
  )
}

function Legend() {
  const items: { label: string; color: string; dashed?: boolean }[] = [
    { label: '남는 돈', color: 'var(--fact)' },
    { label: '빠지는 돈', color: 'var(--ink-3)' },
    { label: '영업 밖에서 들어온 돈', color: 'var(--hyp)' },
    { label: '차액·추정', color: 'var(--ink-3)', dashed: true },
  ]
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted-foreground">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">
          <span className={cn("inline-block h-2 w-5 rounded-sm", it.dashed && "border border-dashed")}
                style={{ backgroundColor: it.dashed ? 'transparent' : it.color, borderColor: it.dashed ? it.color : undefined }} />
          {it.label}
        </span>
      ))}
      <span className="text-caption text-muted-foreground">· 비중 5% 미만은 '그 외'로 묶음(펼치기 가능)
        <InfoTip label="비중 5% 미만 설명">
          매출 대비 비중이 5% 미만인 비용 항목은 공간을 아끼려고 '그 외'로 묶여 있습니다. 노드를 눌러 펼칠 수 있습니다(후속 단계).
        </InfoTip>
      </span>
    </div>
  )
}

function SourceLine({ d, market }: { d: IncomeFlowResponse; market: 'kr' | 'us' }) {
  const parts: string[] = []
  parts.push(market === 'kr'
    ? `${fmtQuarterLabel(d.period, 'kr')} ${d.stage === 'preliminary' ? '잠정실적 공시' : '분기보고서'}${d.as_of ? ` · ${d.as_of} 발표` : ''}`
    : `${fmtQuarterLabel(d.period, 'us')} 10-Q GAAP 손익계산서`)
  if (d.degraded.length) parts.push(`빠진 세부: ${d.degraded.join(', ')}`)
  for (const n of d.notes) parts.push(n)
  return <p className="text-caption text-muted-foreground">출처: {parts.join(' · ')}</p>
}
