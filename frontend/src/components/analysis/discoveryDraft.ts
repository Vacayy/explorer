import type { StrategyCondition, StrategyDefinition, AnalysisSpec } from '@/components/analysis/types'

export interface SearchDraft { question: string; asOf: string; within: number }
export interface PurposeDraft { conditions: StrategyCondition[]; market: AnalysisSpec['market']; minimumCap: string; asOf: string }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const day = (value: unknown) => typeof value === 'string' && (value === '' || /^\d{4}-\d{2}-\d{2}$/.test(value))
export function isSearchDraft(value: unknown): value is SearchDraft {
  return object(value) && typeof value.question === 'string' && value.question.length <= 12000 && day(value.asOf) && Number.isInteger(value.within) && Number(value.within) >= 1 && Number(value.within) <= 250
}
export function isPurposeDraft(value: unknown): value is PurposeDraft {
  return object(value) && ['all', 'KOSPI', 'KOSDAQ'].includes(String(value.market)) && day(value.asOf)
    && typeof value.minimumCap === 'string' && value.minimumCap.length <= 20
    && Array.isArray(value.conditions) && value.conditions.length <= 12
    && value.conditions.every(c => object(c) && typeof c.strategy_id === 'string' && object(c.params) && Number.isInteger(c.within_days) && Number(c.within_days) >= 0 && Number(c.within_days) <= 250
      && Object.values(c.params).every(v => typeof v === 'string' || typeof v === 'boolean' || (typeof v === 'number' && Number.isFinite(v))))
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
