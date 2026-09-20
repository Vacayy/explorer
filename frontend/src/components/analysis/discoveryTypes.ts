import type { AnalysisSpec } from '@/components/analysis/types'

export interface SavedStrategy {
  id: string
  name: string
  purpose: string
  current_version: number
  versions: { number: number; spec: AnalysisSpec; question: string; date_policy: 'latest' | 'fixed'; source_run_id: string; created_at: string; as_of?: string; name?: string; purpose?: string }[]
  created_at: string
  updated_at: string
}

export interface DiscoveryRecommendation {
  id: string
  name: string
  purpose: string
  reason: string
  limitations: string[]
  spec: AnalysisSpec
  availability: string | Record<string, unknown>
}

export interface DiscoveryNote {
  id: string
  revision: number
  reason: string
  assumptions: string
  invalidation: string
  watch_items: string[]
  created_at: string
}

export interface ResearchEvidence {
  id: string
  title: string
  published_at: string | null
  url: string | null
  excerpt: string
  kind: string
  time_precision: string
  source: string | Record<string, unknown>
  warnings?: string[]
  values?: Record<string, unknown>[]
  hs_code?: string
  period?: string
  unit?: string
}

export interface ResearchRun {
  id: string
  status: 'queued' | 'running' | 'partial' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  question: string
  as_of: string | null
  created_at: string
  updated_at: string
  phase?: 'preparing' | 'reading' | 'analyzing' | 'complete'
  preparation?: {
    status: string
    started_at?: string
    completed_at?: string
    items: {
      id: string
      label: string
      status: 'pending' | 'checking' | 'collecting' | 'available' | 'collected' | 'unpublished' | 'unsupported' | 'failed'
      detail?: string
    }[]
  }
  error?: string | null
  packet?: {
    as_of: string
    created_at: string
    question: string
    company: unknown
    lanes: { id: 'market' | 'industry' | 'earnings' | 'call' | 'trade'; label: string; status: string; items: ResearchEvidence[]; warnings: string[] }[]
    warnings: string[]
  }
  result?: {
    summary: string
    claims: { text: string; kind: 'fact' | 'source_claim' | 'inference' | 'unknown'; evidence_ids: string[] }[]
    questions: string[]
    limitations: string[]
  }
  changes?: { added_ids: string[]; removed_ids: string[]; changed_ids?: string[]; previous_run_id: string | null }
}

export interface DiscoveryCase {
  id: string
  stock_code: string
  name: string
  source_run_id: string
  discovery: {
    question: string; spec: AnalysisSpec; as_of: string; snapshot_id: string; evidence: unknown
    saved_strategy?: { id: string; version: number; name: string; date_policy: 'latest' | 'fixed' } | null
    warnings?: string[]
    counts?: { universe: number; matched: number; excluded: number }
    unsupported_conditions?: string[]
  }
  question: string
  notes: DiscoveryNote[]
  research_runs: ResearchRun[]
  created_at: string
  updated_at: string
}
