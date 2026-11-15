/**
 * 분기 손익 흐름 — 프런트 레이아웃·포맷 헬퍼(ia-redesign §4.13).
 *
 * 백엔드가 raw 금액·이익률·YoY·QoQ·콜아웃까지 완성해 돌려주므로 프런트 테스트는:
 * - fmtMoney: 단위 자동 전환(KRW 조/억, USD $B/$M)
 * - fmtQuarterLabel: KR/US 분기 포맷 (키 → 사람이 읽는 라벨)
 * - layoutSankey: 열 좌표와 띠 경로. 핵심은 "띠 높이 = 노드 높이"가 유지되는지(같은 스케일)
 *
 * 서버 쪽 수지·콜아웃 규칙은 backend/tests/test_income_flow.py에서 본다.
 */
import { describe, it, expect } from 'vitest'
import { fmtMoney, fmtQuarterLabel } from '../src/components/financials/flowFormat'
import { layoutSankey, layoutSankeyLabels } from '../src/components/financials/sankeyLayout'
import type { FlowNode, FlowLink } from '../src/types'

describe('fmtMoney', () => {
  it('KRW 조 단위 전환', () => {
    expect(fmtMoney(79.3e12, 'KRW')).toBe('79.3조')
    expect(fmtMoney(1.5e12, 'KRW')).toBe('1.5조')
  })
  it('KRW 억 단위 전환', () => {
    expect(fmtMoney(5.4e11, 'KRW')).toMatch(/억$/)
    expect(fmtMoney(1.2e8, 'KRW')).toMatch(/억$/)
  })
  it('USD $B 단위 전환', () => {
    expect(fmtMoney(96.221e9, 'USD')).toBe('$96.2B')
    expect(fmtMoney(7.773e9, 'USD')).toBe('$7.8B')
  })
  it('USD $M 단위 (1B 미만)', () => {
    expect(fmtMoney(1.354e9, 'USD')).toBe('$1.4B')  // 1B 이상이면 $B로 유지
    expect(fmtMoney(5.0e8, 'USD')).toBe('$500M')
  })
})

describe('fmtQuarterLabel', () => {
  it('KR: YY.MM → 연 Q', () => {
    expect(fmtQuarterLabel('26.06', 'kr')).toBe('2026 Q2')
    expect(fmtQuarterLabel('25.12', 'kr')).toBe('2025 Q4')
  })
  it('US: YYYY-MM → FY Q', () => {
    expect(fmtQuarterLabel('2026-09', 'us')).toBe('FY26 Q3')
    expect(fmtQuarterLabel('2026-06', 'us')).toBe('FY26 Q2')
  })
})

describe('layoutSankey', () => {
  const nodes: FlowNode[] = [
    { id: 'revenue', label: '매출', value: 100, column: 1, kind: 'revenue' },
    { id: 'cogs', label: '매출원가', value: 25, column: 2, kind: 'cost' },
    { id: 'gross_profit', label: '매출총이익', value: 75, column: 2, kind: 'keep' },
    { id: 'op_income', label: '영업이익', value: 70, column: 3, kind: 'keep' },
    { id: 'opex_rnd', label: 'R&D', value: 5, column: 3, kind: 'cost' },
  ]
  const links: FlowLink[] = [
    { source: 'revenue', target: 'cogs', value: 25 },
    { source: 'revenue', target: 'gross_profit', value: 75 },
    { source: 'gross_profit', target: 'op_income', value: 70 },
    { source: 'gross_profit', target: 'opex_rnd', value: 5 },
  ]

  it('모든 노드에 x·y·h가 채워진다', () => {
    const laid = layoutSankey(nodes, links, { width: 800, height: 400 })
    expect(laid.nodes).toHaveLength(nodes.length)
    for (const n of laid.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0)
      expect(n.y).toBeGreaterThanOrEqual(0)
      expect(n.h).toBeGreaterThan(0)
    }
  })

  it('열이 많을수록 x가 커진다', () => {
    const laid = layoutSankey(nodes, links, { width: 800, height: 400 })
    const byId: Record<string, number> = {}
    for (const n of laid.nodes) byId[n.id] = n.x
    expect(byId.revenue).toBeLessThan(byId.gross_profit)
    expect(byId.gross_profit).toBeLessThan(byId.op_income)
  })

  it('같은 열의 cost는 아래, keep은 위', () => {
    const laid = layoutSankey(nodes, links, { width: 800, height: 400 })
    const byId = Object.fromEntries(laid.nodes.map(n => [n.id, n]))
    // col 2: gross_profit(keep) y < cogs(cost) y
    expect(byId.gross_profit.y).toBeLessThan(byId.cogs.y)
    // col 3: op_income(keep) y < opex_rnd(cost) y
    expect(byId.op_income.y).toBeLessThan(byId.opex_rnd.y)
  })

  it('띠 높이가 값에 비례한다 (같은 스케일 유지)', () => {
    const laid = layoutSankey(nodes, links, { width: 800, height: 400 })
    const links25 = laid.links.find(l => l.source === 'revenue' && l.target === 'cogs')!
    const links75 = laid.links.find(l => l.source === 'revenue' && l.target === 'gross_profit')!
    const h25 = links25.sy1 - links25.sy0
    const h75 = links75.sy1 - links75.sy0
    // 75/25 = 3배 ±5%
    expect(h75 / h25).toBeCloseTo(3, 0)
  })

  it('띠 path는 cubic Bezier M·C·L·C·Z로 끝난다', () => {
    const laid = layoutSankey(nodes, links, { width: 800, height: 400 })
    for (const l of laid.links) {
      expect(l.path.startsWith('M')).toBe(true)
      expect(l.path.endsWith(' Z')).toBe(true)
      expect(l.path).toContain('C')
      expect(l.path).toContain('L')
    }
  })
})

it('keeps edge labels inside and separates adjacent small cost labels without changing flow geometry', () => {
 const nodes: FlowNode[] = [
  {id:'segment',label:'Data Center',value:96,column:0,kind:'revenue'},
  {id:'revenue',label:'Revenue',value:100,column:1,kind:'revenue'},
  {id:'rnd',label:'R&D',value:7,column:3,kind:'cost'},
  {id:'sga',label:'SG&A',value:1.4,column:3,kind:'cost'},
  {id:'net',label:'Net income',value:50,column:5,kind:'keep'},
 ]
 const laid = layoutSankey(nodes,[],{width:980,height:440})
 const before = JSON.stringify(laid)
 const labels = layoutSankeyLabels(laid.nodes,440,()=>3)
 expect(labels.get('segment')!.x).toBeGreaterThan(0)
 expect(labels.get('segment')!.anchor).toBe('start')
 expect(labels.get('net')!.x).toBeGreaterThan(980)
 expect(labels.get('net')!.x).toBeLessThan(1160)
 expect(labels.get('net')!.anchor).toBe('start')
 const costs = ['rnd','sga'].map(id=>labels.get(id)!.y).sort((a,b)=>a-b)
 expect(costs[1]-costs[0]).toBeGreaterThanOrEqual(82)
 for(const l of labels.values()) { expect(l.y-12).toBeGreaterThanOrEqual(0);expect(l.y+62).toBeLessThan(440) }
 expect(JSON.stringify(laid)).toBe(before)
})
