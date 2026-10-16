import { test } from 'node:test'
import assert from 'node:assert/strict'
import { scenarioGroup } from '../src/components/analysis/discoveryScenarios.ts'

// 묶음 정본은 서버 추천 목록(PRESETS) — 여기선 그 목록의 scenario로 범위를 고르는 규칙만 본다
const PRESETS = [
  { id: 'new-high', scenario: 'rising' },
  { id: 'lens-oversold-exit', scenario: 'recovery' },
  { id: 'lens-squeeze', scenario: 'other' },
  { id: 'lens-pullback-20', scenario: 'rising' },
]

test('discovery defaults to upward scenarios without guessing the direction of neutral observations', () => {
  assert.equal(scenarioGroup(null, ''), 'rising')
  assert.equal(scenarioGroup('invalid', '', PRESETS), 'rising')
})

test('old purpose links restore a matching group while explicit all view stays all', () => {
  assert.equal(scenarioGroup(null, 'lens-oversold-exit', PRESETS), 'recovery')
  assert.equal(scenarioGroup(null, 'lens-squeeze', PRESETS), 'all')
  assert.equal(scenarioGroup('all', 'lens-pullback-20', PRESETS), 'all')
  assert.equal(scenarioGroup(null, 'known', PRESETS), 'rising')
})
