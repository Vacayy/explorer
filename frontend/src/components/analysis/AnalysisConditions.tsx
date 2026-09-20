import { Badge } from '@/components/ui/badge'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '@/api/client'
import { formatKrw } from '@/utils/format'
import type { AnalysisSpec, StrategyDefinition, StrategyExpression } from './types'

function ExpressionCondition({ node, definitions }: { node: StrategyExpression; definitions: StrategyDefinition[] }) {
  if (node.op === 'condition') {
    const definition = definitions.find(item => item.id === node.condition.strategy_id)
    return <span>{definition?.label ?? node.condition.strategy_id} · {node.condition.within_days > 1 ? `최근 ${node.condition.within_days}거래일` : '판정일'}{Object.keys(node.condition.params).length > 0 && <span className="text-muted-foreground"> ({Object.entries(node.condition.params).map(([key, value]) => `${definition?.parameters[key]?.label ?? key}: ${String(value)}`).join(', ')})</span>}</span>
  }
  const children = 'children' in node ? node.children : [node.child]
  const label = node.op === 'and' ? '모두 충족' : node.op === 'or' ? '하나 이상 충족' : node.op === 'not' ? '다음 조건 제외' : node.op === 'consecutive' ? `${node.days}거래일 연속 유지` : `최근 ${node.within_days}거래일 안에 다음 순서 · 사건 간 최대 ${node.max_gap_days}거래일 · ${node.allow_same_day ? '당일 허용' : '다른 거래일'}`
  return <div className="space-y-2"><p className="font-medium">{label}</p><ol className="space-y-2 border-l-2 border-border pl-4">{children.map((child, index) => <li key={index}><ExpressionCondition node={child} definitions={definitions} /></li>)}</ol></div>
}

export function AnalysisConditions({ spec, priceAdjustment, definitions: supplied = [] }: { spec: AnalysisSpec; priceAdjustment?: string; definitions?: StrategyDefinition[] }) {
  const catalog = useQuery({ queryKey: ['market-analysis', 'strategies'], queryFn: async ({ signal }): Promise<{ items: StrategyDefinition[] }> => { const response = await fetch(`${API_BASE}/api/analysis/strategies`, { signal }); if (!response.ok) throw new Error('전략 이름을 불러오지 못했습니다.'); return response.json() }, enabled: !supplied.length && (!!spec.expression || !!spec.strategy_conditions?.length), staleTime: 60_000 })
  const definitions = supplied.length ? supplied : catalog.data?.items ?? []
  const conditions = [
    spec.market === 'all' ? '국내 전체 시장' : spec.market,
    `시총 ${formatKrw(spec.min_market_cap)}원 이상`,
    ...(spec.strategy_conditions ?? []).map(condition => {
      const definition = definitions.find(item => item.id === condition.strategy_id)
      const settings = Object.entries(condition.params).map(([key, value]) => `${definition?.parameters[key]?.label ?? key} ${String(value)}`).join(' · ')
      return `${definition?.label ?? condition.strategy_id} · ${condition.within_days > 1 ? `최근 ${condition.within_days}거래일` : '기준일'}${settings ? ` · ${settings}` : ''}`
    }),
    ...(spec.pattern === 'inverse_head_shoulders' ? [`역헤드앤숄더 · 최근 ${spec.lookback_days}거래일 ${spec.window_scope === 'formation' ? '패턴 형성' : '넥라인 돌파'}`] : []),
    ...(spec.require_52w ? [`${spec.pattern === 'none' ? '' : `돌파 ${spec.include_same_day ? '당일 포함 이후' : '다음 날부터'} · `}52주 신고가`] : []),
    ...(spec.require_ma ? [`최근 ${spec.hold_days}거래일 · ${spec.price_basis === 'low' ? '장중 저가' : '종가'} ≥ SMA${spec.ma_period}`] : []),
  ]
  return <section aria-label="적용한 분석 조건" className="space-y-2">
    <div className="flex flex-wrap gap-2">{conditions.map(condition => <Badge key={condition} variant="secondary" className="whitespace-normal font-normal">{condition}</Badge>)}</div>
    {spec.expression && <div className="rounded-lg bg-muted/50 p-3 text-caption"><ExpressionCondition node={spec.expression} definitions={definitions} /></div>}
    {spec.universe_codes != null && <p className="text-caption text-muted-foreground">이전 후보 {spec.universe_codes.length}종목으로 검색 범위 제한</p>}
    <p className="text-caption text-muted-foreground">
      {priceAdjustment === 'adjusted' ? '수정주가 이력 사용' : '수정주가 여부 미확인'}
      {spec.pattern === 'inverse_head_shoulders' && ` · 피벗 폭 ${spec.pivot_width} · 어깨 허용 오차 ${Math.round(spec.shoulder_tolerance * 100)}%`}
      {!spec.expression && !!spec.strategy_conditions?.length && ' · 선택한 조건 모두 만족 (AND)'}
    </p>
    {spec.require_52w && <p className="text-caption text-muted-foreground">52주 신고가: 판정일 종가가 그날을 제외한 직전 365일의 고가 최댓값을 초과한 경우입니다.</p>}
  </section>
}
