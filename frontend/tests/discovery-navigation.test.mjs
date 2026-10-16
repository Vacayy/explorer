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

test('company tabs preserve discovery date view and scan settings without implying a research case', () => {
  const tabs = analyzeTabs('005930', '?source_run=run-1&scan=1&scan_at=discovery&scan_within=10&scan_chart=0&q=discard&return=https://example.com')
  assert.equal(tabs[0].label, '개요')
  for (const tab of tabs) {
    const url = new URL(tab.path, 'http://localhost')
    assert.equal(url.searchParams.get('source_run'), 'run-1')
    assert.equal(url.searchParams.get('scan_at'), 'discovery')
    assert.equal(url.searchParams.get('scan'), '1')
    assert.equal(url.searchParams.get('scan_within'), '10')
    assert.equal(url.searchParams.get('scan_chart'), '0')
    assert.equal(url.searchParams.has('q'), false)
    assert.equal(url.searchParams.has('return'), false)
  }
})

test('company tabs retain the candidate comparison and order only with a source run', () => {
  const query = '?source_run=r1&source_compare=005930,000660&source_sort=cap_asc&sort=unrelated'
  for (const tab of analyzeTabs('005930', query)) {
    const params = new URL(tab.path, 'http://localhost').searchParams
    assert.equal(params.get('source_compare'), '005930,000660')
    assert.equal(params.get('source_sort'), 'cap_asc')
    assert.equal(params.has('sort'), false)
  }
  assert.equal(companyResearchSearch('?source_compare=005930,000660&source_sort=cap_asc'), '')
})

test('company tabs preserve the primary structure view and its drawing parameters', () => {
  for (const tab of analyzeTabs('005930', '?scan=1&scan_view=structure&structure_kind=profile&structure_window=1y&structure_swing=10&structure_fit=regression&kind=unrelated')) {
    const params = new URL(tab.path, 'http://localhost').searchParams
    assert.equal(params.get('scan_view'), 'structure')
    assert.equal(params.get('structure_kind'), 'profile')
    assert.equal(params.get('structure_window'), '1y')
    assert.equal(params.get('structure_swing'), '10')
    assert.equal(params.get('structure_fit'), 'regression')
    assert.equal(params.has('kind'), false)
  }
})
