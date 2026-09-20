import { test } from 'node:test'
import assert from 'node:assert/strict'
import { analyzeTabs, companyResearchSearch, getActiveMode, MODES } from '../src/components/layout/navConfig.ts'

test('discovery has a primary entry and backtests remain in its context', () => {
  assert.equal(MODES.find(mode => mode.key === 'discover')?.path, '/discover')
  assert.equal(getActiveMode('/discover'), 'discover')
  assert.equal(getActiveMode('/analysis/backtests'), 'discover')
  assert.equal(getActiveMode('/chat'), 'chat')
})

test('company tab changes preserve research selection but never unrelated search filters', () => {
  const tabs = analyzeTabs('403870', '?discovery=case-1&research=run-2&researchTab=sources&lane=earnings&q=discard&return=https://example.com')
  assert.equal(tabs[0].label, '기업 조사')
  for (const tab of tabs) {
    const url = new URL(tab.path, 'http://localhost')
    assert.equal(url.searchParams.get('discovery'), 'case-1')
    assert.equal(url.searchParams.get('research'), 'run-2')
    assert.equal(url.searchParams.get('researchTab'), 'sources')
    assert.equal(url.searchParams.get('lane'), 'earnings')
    assert.equal(url.searchParams.has('q'), false)
    assert.equal(url.searchParams.has('return'), false)
  }
})

test('ordinary company navigation has no accidental discovery state', () => {
  assert.equal(companyResearchSearch('?research=orphan&lane=earnings'), '')
  assert.equal(analyzeTabs('005930')[0].label, '개요')
  assert.equal(analyzeTabs('005930')[1].path, '/analyze/005930/financials')
})
