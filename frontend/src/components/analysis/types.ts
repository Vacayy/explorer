import type { ServerToClientMessage } from '@a2ui/react'

export type RunStatus = 'queued' | 'preparing' | 'running' | 'waiting_input' | 'completed' | 'partial' | 'blocked' | 'failed' | 'cancelled' | 'interrupted'

export interface AnalysisSpec {
  mode?: 'pattern' | 'catalog'
  strategy_conditions?: StrategyCondition[]
  expression?: StrategyExpression | null
  universe_codes?: string[] | null
  market: 'all' | 'KOSPI' | 'KOSDAQ'
  as_of: string | null
  min_market_cap: number
  pattern: 'inverse_head_shoulders' | 'none'
  lookback_days: number
  window_scope: 'breakout' | 'formation'
  pivot_width: number
  shoulder_tolerance: number
  require_52w: boolean
  include_same_day: boolean
  ma_period: number
  hold_days: number
  price_basis: 'close' | 'low'
  require_ma: boolean
  price_adjustment: 'unknown' | 'adjusted'
}

export type StrategyExpression =
  | { op: 'condition'; condition: StrategyCondition }
  | { op: 'and'; children: StrategyExpression[] }
  | { op: 'or'; children: StrategyExpression[] }
  | { op: 'not'; child: StrategyExpression }
  | { op: 'sequence'; children: StrategyExpression[]; within_days: number; max_gap_days: number; allow_same_day: boolean }
  | { op: 'consecutive'; child: StrategyExpression; days: number }

export interface StrategyCondition {
  strategy_id: string
  params: Record<string, unknown>
  within_days: number
}

export interface StrategyParameter {
  type: 'integer' | 'number' | 'string' | 'boolean'
  label: string
  min?: number
  max?: number
  step?: number
  options?: string[]
}

export interface StrategyDefinition {
  id: string
  label: string
  category: '시세동향' | '지표신호' | '순위종목'
  timeframe: '1d' | '10m'
  description: string
  formula: string
  defaults: Record<string, unknown>
  parameters: Record<string, StrategyParameter>
  required_data: string[]
  available: boolean
}

export interface StrategyCheck {
  label?: string
  status?: string
  value?: unknown
  reference?: unknown
  date?: string | null
  rank?: number | null
  reason?: string | null
  estimated?: boolean
}

export interface AnalysisCandidate {
  code: string
  name: string
  market_cap: number | null
  status?: 'provisional' | 'verified'
  breakout_date?: string | null
  high52_date?: string | null
  checks: Record<string, unknown>
  pattern?: Record<string, unknown> | null
}

export interface AnalysisResult {
  status: string
  as_of: string
  spec: AnalysisSpec
  counts: { universe: number; evaluated: number; matched: number; excluded: number }
  items: AnalysisCandidate[]
  excluded: { code: string; name?: string; reason: string; first_date?: string; last_date?: string; required_start?: string; conditions?: { strategy_id: string; label: string; reason: string }[] }[]
  warnings: string[]
  unsupported_conditions?: string[]
  strategy_definitions?: StrategyDefinition[]
}

export interface AnalysisPending {
  id: string
  question: string
  a2ui: ServerToClientMessage[]
  surfaceId: string
}

export interface AnalysisRun {
  id: string
  question: string
  status: RunStatus
  phase: string
  created_at: string
  updated_at: string
  spec: AnalysisSpec | null
  result: AnalysisResult | null
  pending: AnalysisPending | null
  error: string | null
  cost_usd: number
  cost_uncertain?: boolean
  active_seconds: number
  steps: number
  artifacts: { id: string; name: string; kind: string; size: number }[]
  snapshot: { as_of: string; rows: number; stocks: number; warnings?: string[]; price_adjustment?: { status: string; source: string } | null } | null
  lineage?: { parent_run_id: string; scope: 'universe' | 'candidates'; date_policy: 'same' | 'latest'; changes: { field: string; before: unknown; after: unknown }[]; parent_question?: string; parent_as_of?: string }
  saved_strategy?: { id: string; version: number; name: string; date_policy: 'latest' | 'fixed' }
}

export interface AnalysisChart {
  code: string
  name: string
  prices: { time: string; open: number; high: number; low: number; close: number; volume: number }[]
  ma: { time: string; value: number }[]
  markers: { time: string; label: string; price: number; kind: string }[]
  neckline: { time: string; value: number }[]
}
