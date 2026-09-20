import { test } from 'node:test'
import assert from 'node:assert/strict'
import { eventLog, eventRun, isTerminal, newestRun, parseAnalysisEvent, streamCanRest } from '../src/components/analysis/events.ts'

test('AG-UI parsing preserves replay sequence and rejects malformed or unknown envelopes', () => {
  const raw = { type: 'CUSTOM', name: 'analysis.state', sequence: 14, value: { id: 'run-a' } }
  assert.deepEqual(parseAnalysisEvent(JSON.stringify(raw)), raw)
  assert.equal(parseAnalysisEvent('{"type":"CUSTOM","seq":7,"name":"analysis.code","value":"print(1)"}').sequence, 7)
  for (const value of ['not json', '{}', '{"type":"CUSTOM","sequence":-1}', '{"type":"not-an-event","sequence":1}', '{"type":"CUSTOM","sequence":1.5}']) assert.equal(parseAnalysisEvent(value), null)
})

test('state events cannot cross run boundaries or infer completion from transport finish', () => {
  const run = { id: 'run-a', status: 'partial', updated_at: '2026-09-18T10:00:00Z' }
  assert.equal(eventRun({ type: 'CUSTOM', sequence: 1, name: 'analysis.state', value: run }, 'run-a'), run)
  assert.equal(eventRun({ type: 'CUSTOM', sequence: 1, name: 'analysis.state', value: run }, 'run-b'), null)
  assert.equal(eventRun({ type: 'RUN_FINISHED', sequence: 2, runId: 'run-a' }, 'run-a'), null)
  assert.equal(isTerminal('waiting_input'), false)
  assert.equal(isTerminal('partial'), true)
})

test('old replay cannot undo cancellation or replace a newer persisted state', () => {
  const cancelled = { id: 'run-a', status: 'cancelled', updated_at: '2026-09-18T10:01:00Z' }
  const stale = { ...cancelled, status: 'running', updated_at: '2026-09-18T10:00:00Z' }
  assert.equal(newestRun(cancelled, stale), cancelled)
  assert.equal(newestRun(cancelled, { ...stale, updated_at: cancelled.updated_at }), cancelled)
  const completed = { ...cancelled, status: 'completed', updated_at: '2026-09-18T10:02:00Z' }
  assert.equal(newestRun(stale, completed), completed)
})

test('execution log is bounded and does not expose model thinking or duplicate full state', () => {
  assert.equal(eventLog({ type: 'THINKING_TEXT_MESSAGE_CONTENT', sequence: 1, delta: 'private' }), null)
  assert.equal(eventLog({ type: 'CUSTOM', sequence: 2, name: 'analysis.state', value: {} }), null)
  assert.ok(eventLog({ type: 'CUSTOM', sequence: 3, name: 'analysis.code', value: 'x'.repeat(20000) }).length <= 16000)
  assert.match(eventLog({ type: 'TOOL_CALL_RESULT', sequence: 4, content: 'observed result' }), /observed result/)
})

test('replay of an old interrupt finish does not close a resumed running stream', () => {
  const resumed = { id: 'run-a', status: 'running', updated_at: '2026-09-18T10:02:00Z' }
  const oldWaiting = { ...resumed, status: 'waiting_input', updated_at: '2026-09-18T10:00:00Z' }
  const stateAtOldFinish = newestRun(resumed, oldWaiting)
  assert.equal(streamCanRest(stateAtOldFinish.status), false)
  assert.equal(streamCanRest('waiting_input'), true)
  assert.equal(streamCanRest('partial'), true)
  assert.equal(streamCanRest(undefined), false)
})
