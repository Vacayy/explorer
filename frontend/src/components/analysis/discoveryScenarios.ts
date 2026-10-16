export const SCENARIO_GROUPS = [
  { id: 'rising', label: '상승 후보' },
  { id: 'recovery', label: '반등·전환' },
  { id: 'all', label: '모든 상황' },
] as const
export type ScenarioGroup = typeof SCENARIO_GROUPS[number]['id']

/** Copy describes the server preset, without treating non-directional observations as bullish. */
export const DISCOVERY_SCENARIOS = [
  { id: 'high-20d-volume', group: 'rising', name: '거래량을 동반한 돌파', description: '20일 고점을 넘으며 거래량이 증가한 종목', tag: '돌파' },
  { id: 'new-high', group: 'rising', name: '52주 신고가 갱신', description: '지난 1년의 고점을 새로 넘어선 종목', tag: '신고가' },
  { id: 'lens-range-break', group: 'rising', name: '횡보 구간의 돌파', description: '수평으로 움직이던 박스권의 윗선을 넘은 종목', tag: '돌파' },
  { id: 'lens-momentum-strong', group: 'rising', name: '강한 상승 추세', description: '장기선 위에서 모멘텀이 양이고 추세 강도가 높은 종목', tag: '추세 지속' },
  { id: 'lens-pullback-20', group: 'rising', name: '상승 흐름의 되돌림', description: '200일선 위에서 20일선 가까이 돌아온 종목', tag: '눌림' },
  { id: 'lens-profile-above', group: 'rising', name: '매물대 위로 올라선 흐름', description: '장기선 위에서 60일 매물대 중심선을 넘어선 종목', tag: '가격대 돌파' },
  { id: 'reversal-confirmed', group: 'recovery', name: '전환 후 유지되는 흐름', description: '방향 전환 뒤 일정 기간 조건을 유지한 종목', tag: '전환 확인' },
  { id: 'lens-oversold-exit', group: 'recovery', name: '과매도 후 회복', description: '과매도를 벗어나 스윙 저점을 높이는 종목', tag: '회복' },
  { id: 'lens-spring', group: 'recovery', name: '저점 이탈 후 재진입', description: '직전 저점을 깼다가 다시 위로 마감한 종목', tag: '가격 회복' },
  { id: 'lens-reenter-lower', group: 'recovery', name: '밴드 하단에서 복귀', description: '볼린저 하단 밖에서 밴드 안으로 돌아온 종목', tag: '평균 회귀' },
  { id: 'lens-squeeze', group: 'other', name: '변동성이 좁아진 구간', description: '밴드 폭이 좁아진 종목 · 다음 방향은 미정', tag: '방향 미정' },
  { id: 'volume-growth', group: 'other', name: '거래량이 급증한 흐름', description: '전일 대비 거래량 증가율 상위 · 가격 방향은 별도 확인', tag: '거래 변화' },
] as const

export function scenarioGroup(value: string | null, intent: string): ScenarioGroup {
  if (value === 'rising' || value === 'recovery' || value === 'all') return value
  const group = DISCOVERY_SCENARIOS.find(item => item.id === intent)?.group
  return group === 'other' ? 'all' : group ?? 'rising'
}
