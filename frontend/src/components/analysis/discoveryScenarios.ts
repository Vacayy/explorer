/** 빠른 시작 범위 — 묶음 자체(이름·조건·범위)는 서버 추천 목록 하나(discovery_service.PRESETS)가 정본이다 */
export const SCENARIO_GROUPS = [
  { id: 'rising', label: '상승 후보' },
  { id: 'recovery', label: '반등·전환' },
  { id: 'all', label: '모든 상황' },
] as const
export type ScenarioGroup = typeof SCENARIO_GROUPS[number]['id']

/** ?scenario= 우선, 없으면 ?intent=(옛 목적 링크)의 묶음 범위. 방향 미정(other)은 '모든 상황'으로 */
export function scenarioGroup(value: string | null, intent: string, presets: readonly { id: string; scenario?: string }[] = []): ScenarioGroup {
  if (value === 'rising' || value === 'recovery' || value === 'all') return value
  const scenario = presets.find(item => item.id === intent)?.scenario
  return scenario === 'other' ? 'all' : scenario === 'recovery' ? 'recovery' : 'rising'
}
