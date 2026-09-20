export interface BacktestSpec {
  start_date: string
  split_date: string
  end_date: string
  initial_cash: number
  max_positions: number
  rebalance_every: number
  buy_cost_bps: number
  sell_cost_bps: number
  min_market_cap: number
  markets: string[]
}

export interface BacktestConfig {
  defaults: BacktestSpec
  strategies: { id: string; label: string; description: string }[]
  limits: Record<string, unknown>
  data: { snapshot_available: boolean; as_of: string | null }
  warnings: string[]
}

export type BacktestStatus = 'queued' | 'preparing' | 'running' | 'partial' | 'failed' | 'cancelled' | 'interrupted'

export interface BacktestEquity {
  date: string
  nav: number
  cash: number
  exposure_pct: number
  drawdown_pct: number
  positions: number
}

export interface BacktestStrategy {
  id: string
  label: string
  metrics: {
    total_return_pct: number
    max_drawdown_pct: number
    exposure_avg_pct: number
    cost_total: number
    trades_count: number
    ending_nav: number
    unfilled_orders: number
    partial_fills?: number
    stale_valuation_days: number
  }
  equity: BacktestEquity[]
  rebalances: {
    signal_date: string
    execution_date: string | null
    candidates: number
    evaluated: number
    unavailable: number
    target_count: number
  }[]
  trades: Record<string, unknown>[]
  holdings: Record<string, unknown>[]
  unfilled?: {
    date: string | null
    signal_date: string
    code: string
    side: 'buy' | 'sell'
    quantity: number
    target_quantity: number
    reason: string
  }[]
}

export interface BacktestSegment {
  id: 'development' | 'holdout'
  label: string
  start_date: string
  end_date: string
  universe: { requested: number; eligible: number; excluded_by_reason: Record<string, number> }
  strategies: BacktestStrategy[]
}

export interface BacktestResult {
  version: string
  spec: BacktestSpec
  warnings: string[]
  provenance: Record<string, unknown>
  segments: BacktestSegment[]
}

export interface BacktestRun {
  id: string
  status: BacktestStatus
  created_at: string
  updated_at: string
  stage: string
  spec: BacktestSpec
  result?: BacktestResult | null
  error: string | { message?: string; [key: string]: unknown } | null
  artifacts: { name: string; label: string; media_type: string; bytes: number }[]
}
