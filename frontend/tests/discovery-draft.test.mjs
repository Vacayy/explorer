import { test } from 'node:test'
import assert from 'node:assert/strict'
import { conditionInputError, comparisonCodes, isFollowupDraft, isPurposeDraft, isSearchDraft, recoveryScope } from '../src/components/analysis/discoveryDraft.ts'

test('comparison URL accepts only result members, without duplicates and at most three', () => {
  assert.deepEqual(comparisonCodes('000001,000001,missing,000002,000003,000004', ['000001', '000002', '000003', '000004']), ['000001', '000002', '000003'])
  assert.deepEqual(comparisonCodes(null, ['000001']), [])
  assert.deepEqual(comparisonCodes('000001', []), [])
})

test('empty results cannot be searched with an empty candidate scope', () => {
  assert.equal(recoveryScope(true, 'candidates'), 'universe')
  assert.equal(recoveryScope(false, 'candidates'), 'candidates')
  assert.equal(recoveryScope(false, 'universe'), 'universe')
})

test('corrupt or out of range session drafts are rejected', () => {
  const valid = { question: '거래량 증가', asOf: '2026-09-18', within: 5 }
  assert.equal(isSearchDraft(valid), true)
  for (const draft of [null, [], {}, { ...valid, within: 0 }, { ...valid, within: 251 }, { ...valid, within: 1.5 }, { ...valid, question: 'a'.repeat(12001) }, { ...valid, asOf: false }]) assert.equal(isSearchDraft(draft), false)
  assert.equal(isFollowupDraft({ question: '조건 완화', scope: 'universe', policy: 'same' }), true)
  assert.equal(isFollowupDraft({ question: '조건 완화', scope: 'all', policy: 'same' }), false)
})

test('purpose drafts preserve partial edits but reject malformed conditions', () => {
  const draft = { market: 'all', asOf: '', minimumCap: '', conditions: [{ strategy_id: 'rsi_oversold', params: { level: 30, period: 14 }, within_days: 0 }] }
  assert.equal(isPurposeDraft(draft), true)
  assert.equal(isPurposeDraft({ ...draft, conditions: [] }), true)
  assert.equal(isPurposeDraft({ ...draft, market: 'NYSE' }), false)
  assert.equal(isPurposeDraft({ ...draft, conditions: [{ ...draft.conditions[0], params: { level: Infinity } }] }), false)
  assert.equal(isPurposeDraft({ ...draft, conditions: Array(13).fill(draft.conditions[0]) }), false)
})


test('collapsed condition fields still block empty, non-finite and out of range submissions', () => {
  const definition = { id: 'rsi', label: 'RSI', parameters: { period: { type: 'integer', label: '기간', min: 2, max: 250 }, level: { type: 'number', label: '기준', min: 0, max: 100 } } }
  const valid = { strategy_id: 'rsi', params: { period: 14, level: 30 }, within_days: 1 }
  assert.equal(conditionInputError(valid, definition), null)
  for (const value of ['', NaN, Infinity, -1, 101]) assert.match(conditionInputError({ ...valid, params: { ...valid.params, level: value } }, definition), /기준/)
  assert.match(conditionInputError({ ...valid, params: { ...valid.params, period: 1.5 } }, definition), /기간/)
  assert.match(conditionInputError({ ...valid, within_days: 0 }, definition), /충족 기간/)
})
