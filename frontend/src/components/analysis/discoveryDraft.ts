import type { StrategyCondition, StrategyDefinition, AnalysisSpec } from '@/components/analysis/types'

export interface SearchDraft { question: string; asOf: string; within: number }
/** off = 쌓아 두었지만 꺼 둔 블록의 strategy_id (워크스페이스에서 넣다 빼기, D-224) */
export interface PurposeDraft { conditions: StrategyCondition[]; market: AnalysisSpec['market']; minimumCap: string; asOf: string; off?: string[] }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const day = (value: unknown) => typeof value === 'string' && (value === '' || /^\d{4}-\d{2}-\d{2}$/.test(value))
export function isSearchDraft(value: unknown): value is SearchDraft {
  return object(value) && typeof value.question === 'string' && value.question.length <= 12000 && day(value.asOf) && Number.isInteger(value.within) && Number(value.within) >= 1 && Number(value.within) <= 250
}
export function isPurposeDraft(value: unknown): value is PurposeDraft {
  return object(value) && ['all', 'KOSPI', 'KOSDAQ'].includes(String(value.market)) && day(value.asOf)
    && typeof value.minimumCap === 'string' && value.minimumCap.length <= 20
    && (value.off === undefined || (Array.isArray(value.off) && value.off.length <= 12 && value.off.every(id => typeof id === 'string')))
    && Array.isArray(value.conditions) && value.conditions.length <= 12
    && value.conditions.every(c => object(c) && typeof c.strategy_id === 'string' && object(c.params) && Number.isInteger(c.within_days) && Number(c.within_days) >= 0 && Number(c.within_days) <= 250
      && Object.values(c.params).every(v => typeof v === 'string' || typeof v === 'boolean' || (typeof v === 'number' && Number.isFinite(v))))
}

export const MAX_STACKED_CONDITIONS = 12
/** The server rejects duplicate strategy ids, so an already stacked block keeps its edited settings. */
export function stackConditions(current: StrategyCondition[], incoming: StrategyCondition[]) {
  const conditions = [...current]
  let duplicate = 0, overflow = 0
  for (const condition of incoming) {
    if (conditions.some(c => c.strategy_id === condition.strategy_id)) duplicate++
    else if (conditions.length >= MAX_STACKED_CONDITIONS) overflow++
    else conditions.push(condition)
  }
  return { conditions, added: conditions.length - current.length, duplicate, overflow }
}

/** 같은 조건 조합인지 — 서버가 숫자 매개변수를 다른 표기(0 ↔ 0.0)로 돌려줘도 같게 본다. */
export function conditionSignature(conditions: StrategyCondition[]): string {
  return JSON.stringify(conditions.map(c => [c.strategy_id, c.within_days,
    Object.keys(c.params).sort().map(key => [key, typeof c.params[key] === 'number' ? Number(c.params[key]) : c.params[key]])]))
}

export function comparisonCodes(value: string | null, available: string[]): string[] {
  return [...new Set((value ?? '').split(','))].filter(code => available.includes(code)).slice(0, 3)
}

export function recoveryScope(empty: boolean, requested: 'candidates' | 'universe') {
  return empty ? 'universe' : requested
}

/** Collapsed editors are unmounted, so native form validity alone is insufficient. */
export function conditionInputError(condition: StrategyCondition, definition: StrategyDefinition): string | null {
  if (!Number.isInteger(condition.within_days) || condition.within_days < 1 || condition.within_days > 250) return `${definition.label}: 충족 기간을 1~250거래일로 입력해 주세요.`
  for (const [key, parameter] of Object.entries(definition.parameters)) {
    const value = condition.params[key]
    const valid = parameter.options ? parameter.options.includes(String(value))
      : parameter.type === 'boolean' ? typeof value === 'boolean'
      : parameter.type === 'string' ? typeof value === 'string' && !!value.trim()
      : typeof value === 'number' && Number.isFinite(value) && (parameter.type !== 'integer' || Number.isInteger(value))
        && (parameter.min == null || value >= parameter.min) && (parameter.max == null || value <= parameter.max)
    if (!valid) return `${definition.label}: ‘${parameter.label}’ 입력값을 확인해 주세요.`
  }
  return null
}

export interface FollowupDraft { question: string; scope: 'candidates' | 'universe'; policy: 'same' | 'latest' }
export function isFollowupDraft(value: unknown): value is FollowupDraft {
  return object(value) && typeof value.question === 'string' && value.question.length <= 12000
    && ['candidates', 'universe'].includes(String(value.scope)) && ['same', 'latest'].includes(String(value.policy))
}
