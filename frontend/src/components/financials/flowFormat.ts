// 분기 손익 흐름 — 포맷 헬퍼. 백엔드가 raw 금액·YoY·QoQ·이익률 다 계산해 돌려주므로 여기선 표시만.
import { MINUS, formatPercent, formatPp } from "@/utils/format"
import type { FlowCallout, FlowNode, IncomeFlowResponse } from "@/types"

/** 금액 → 사람이 읽기 좋은 문자열. KR은 조/억 자동 전환, US는 $B/$M. */
export function fmtMoney(value: number, unit: 'KRW' | 'USD'): string {
  if (!Number.isFinite(value)) return "-"
  if (unit === 'KRW') {
    const abs = Math.abs(value)
    if (abs >= 1e12) return `${(value / 1e12).toFixed(1)}조`
    if (abs >= 1e8) return `${Math.round(value / 1e8).toLocaleString('ko-KR')}억`
    return value.toLocaleString('ko-KR')
  }
  const abs = Math.abs(value)
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(0)}M`
  return `$${value.toLocaleString('en-US')}`
}

/** '26.06' → '2026 Q2' · '2026-06' → 'FY26 Q2'. 둘 다 끝월 기준. */
export function fmtQuarterLabel(q: string, market: 'kr' | 'us'): string {
  const m = market === 'us' ? q.split('-') : q.split('.')
  if (m.length !== 2) return q
  const yy = market === 'us' ? m[0].slice(-2) : m[0]
  const quarter = { '03': 'Q1', '06': 'Q2', '09': 'Q3', '12': 'Q4' }[m[1]] ?? ''
  return market === 'us' ? `FY${yy} ${quarter}` : `20${yy} ${quarter}`
}

/** 섹션 머리 부제 — 기준·분기·단위·발표일. */
export function fmtSubtitle(d: IncomeFlowResponse, market: 'kr' | 'us'): string {
  const parts: string[] = []
  const fsLabel = { CFS: '연결', OFS: '별도', GAAP: 'GAAP' }[d.fs_div]
  parts.push(fsLabel)
  parts.push(fmtQuarterLabel(d.period, market))
  parts.push(market === 'us' ? '단위 $B' : '단위 조원')
  if (d.as_of) parts.push(`${d.as_of.slice(5)} 발표`)
  if (d.stage === 'preliminary') parts.push('(잠정)')
  return parts.join(' · ')
}

/** 노드 보조 줄 — '이익률 75.0% · 이익률 YoY +2.6%p · QoQ +0.1%p' 등 §3 라벨 규칙. */
export function nodeSubText(n: FlowNode): string[] {
  const s = n.subs
  if (!s) return []
  const out: string[] = []
  if (s.margin != null) out.push(`${n.id === 'gross_profit' ? 'GPM' : n.id === 'op_income' ? 'OPM' : '이익률'} ${s.margin.toFixed(1)}%`)
  if (s.margin_yoy_pp != null || s.margin_qoq_pp != null) {
    const parts: string[] = []
    if (s.margin_yoy_pp != null) parts.push(`YoY ${formatPp(s.margin_yoy_pp, 1)}p`)
    if (s.margin_qoq_pp != null) parts.push(`QoQ ${formatPp(s.margin_qoq_pp, 1)}p`)
    if (parts.length) out.push(`이익률 ${parts.join(' · ')}`)
  }
  if (s.yoy != null) out.push(`YoY ${formatPercent(s.yoy)}`)
  if (s.qoq != null) out.push(`QoQ ${formatPercent(s.qoq)}`)
  if (s.share_of_revenue != null) out.push(`매출 대비 ${s.share_of_revenue.toFixed(1)}%`)
  if (s.effective_tax_rate != null) out.push(`실효세율 ${s.effective_tax_rate.toFixed(1)}%`)
  if (s.note) out.push(s.note)
  return out
}

export function calloutLabel(_c: FlowCallout): string {
  return "이번 분기 읽을 점"
}

/** CSS 토큰 변수로 바뀌는 색/불투명도 — §4 */
export const NODE_STYLE: Record<FlowNode['kind'], { fill: string; opacity: number }> = {
  revenue: { fill: 'var(--ink-2)', opacity: 1 },
  keep: { fill: 'var(--fact)', opacity: 1 },
  cost: { fill: 'var(--ink-3)', opacity: 1 },
  inflow: { fill: 'var(--hyp)', opacity: 1 },
}
export const LINK_OPACITY: Record<FlowNode['kind'], number> = {
  revenue: 0.30, keep: 0.30, cost: 0.22, inflow: 0.30,
}
export const _MINUS = MINUS
