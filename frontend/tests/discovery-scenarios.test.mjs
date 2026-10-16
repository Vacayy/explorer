import { test } from 'node:test'
import assert from 'node:assert/strict'
import { DISCOVERY_SCENARIOS, scenarioGroup } from '../src/components/analysis/discoveryScenarios.ts'

test('discovery defaults to upward scenarios without guessing the direction of neutral observations', () => {
  assert.equal(scenarioGroup(null, ''), 'rising')
  assert.equal(scenarioGroup('invalid', ''), 'rising')
  const rising = DISCOVERY_SCENARIOS.filter(item => item.group === 'rising')
  assert.equal(rising.length, 6)
  assert.equal(rising.some(item => ['lens-squeeze', 'volume-growth', 'low-52w'].includes(item.id)), false)
  assert.equal(new Set(DISCOVERY_SCENARIOS.map(item => item.id)).size, DISCOVERY_SCENARIOS.length)
})

test('old purpose links restore a matching group while explicit all view stays all', () => {
  assert.equal(scenarioGroup(null, 'lens-oversold-exit'), 'recovery')
  assert.equal(scenarioGroup(null, 'lens-squeeze'), 'all')
  assert.equal(scenarioGroup('all', 'lens-pullback-20'), 'all')
  assert.equal(scenarioGroup(null, 'known'), 'rising')
})
