import { BaseEventSchema, EventType } from '@ag-ui/core'
import type { AnalysisRun, RunStatus } from './types.ts'

const STATUSES: RunStatus[] = ['queued', 'preparing', 'running', 'waiting_input', 'completed', 'partial', 'blocked', 'failed', 'cancelled', 'interrupted']
const TERMINAL: RunStatus[] = ['completed', 'partial', 'blocked', 'failed', 'cancelled', 'interrupted']

export function isTerminal(status: RunStatus) {
  return TERMINAL.includes(status)
}

export function streamCanRest(status: RunStatus | undefined) {
  return !!status && (isTerminal(status) || status === 'waiting_input')
}

export interface AnalysisEvent {
  type: EventType
  sequence: number
  [key: string]: unknown
}

/** Validate the protocol envelope without losing the server's replay sequence. */
export function parseAnalysisEvent(raw: string): AnalysisEvent | null {
  try {
    const value = JSON.parse(raw)
    const sequence = value?.sequence ?? value?.seq
    if (!BaseEventSchema.safeParse(value).success || !Number.isSafeInteger(sequence) || sequence < 1) return null
    return { ...value, sequence } as AnalysisEvent
  } catch {
    return null
  }
}

export function eventRun(event: AnalysisEvent, runId: string): AnalysisRun | null {
  if (event.type !== EventType.CUSTOM || event.name !== 'analysis.state') return null
  const value = event.value as Partial<AnalysisRun> | null
  if (!value || value.id !== runId || !STATUSES.includes(value.status as RunStatus) || typeof value.updated_at !== 'string') return null
  return value as AnalysisRun
}

/** A replayed older state must never replace a fresh GET or a cancel response. */
export function newestRun(current: AnalysisRun | undefined, incoming: AnalysisRun): AnalysisRun {
  if (!current || current.id !== incoming.id) return incoming
  if (Date.parse(current.updated_at) > Date.parse(incoming.updated_at)) return current
  if (current.updated_at === incoming.updated_at && isTerminal(current.status) && !isTerminal(incoming.status)) return current
  return incoming
}

export function eventLog(event: AnalysisEvent): string | null {
  if (event.type === EventType.CUSTOM && event.name !== 'analysis.state') {
    return `${event.name}: ${typeof event.value === 'string' ? event.value : JSON.stringify(event.value)}`.slice(0, 16_000)
  }
  if (event.type === EventType.STEP_STARTED || event.type === EventType.STEP_FINISHED) return `${event.type === EventType.STEP_STARTED ? '시작' : '완료'} · ${event.stepName ?? ''}`
  if (event.type === EventType.TOOL_CALL_ARGS) return String(event.delta ?? '').slice(0, 16_000)
  if (event.type === EventType.TOOL_CALL_RESULT) return String(event.content ?? '').slice(0, 16_000)
  if (event.type === EventType.RUN_ERROR) return String(event.message ?? '실행 오류')
  // Private model thinking is not user-facing progress or an analysis result.
  return null
}
