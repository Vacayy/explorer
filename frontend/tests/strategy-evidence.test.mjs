import { test } from 'node:test'
import assert from 'node:assert/strict'
import { checkValue, evidenceValue, strategyCheck } from '../src/components/analysis/strategyEvidence.ts'

test('missing strategy data is distinct from a failed condition and unknown evidence', () => {
  assert.equal(checkValue({ status: 'unavailable', reason: 'missing_intraday' }), '판단 불가 · 10분봉 시세 없음')
  assert.equal(checkValue({ status: 'unavailable', reason: 'missing_trading_value' }), '판단 불가 · 실제 거래대금 자료 없음')
  assert.equal(checkValue({ status: 'fail', value: 0 }), '탈락')
  assert.equal(checkValue({ value: 123 }), '미검증')
  assert.equal(checkValue(null), '미검증')
  assert.equal(checkValue({ passed: true }), '통과')
})

test('evidence retains meaningful zero values without printing invalid numbers', () => {
  assert.equal(evidenceValue(0), '0')
  assert.equal(evidenceValue(123456.789), '123,456.789')
  assert.equal(evidenceValue('2026-09-18'), '2026-09-18')
  for (const value of [null, undefined, NaN, Infinity, {}]) assert.equal(evidenceValue(value), '—')
  assert.deepEqual(strategyCheck(true), {})
  assert.deepEqual(strategyCheck(null), {})
  assert.equal(strategyCheck({ status: 'pass', rank: 1 }).rank, 1)
})
