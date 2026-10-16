import { test } from 'node:test'
import assert from 'node:assert/strict'
import { locate, SECTIONS } from '../src/components/layout/navConfig.ts'

// docs/specs/app-shell.md §2 판정 표
const CASES = [
  ['/home', '', 'home', 'dashboard'],
  ['/home', '?home_view=market', 'home', 'dashboard'],
  ['/home', '?home_view=feed', 'canvas', 'feed'],
  ['/home/briefing', '', 'home', 'briefing'],
  ['/home/risk', '', 'home', 'risk'],
  ['/retail', '', 'home', 'risk'],
  ['/home/macro', '', 'home', 'macro'],
  ['/feed', '?view=documents', 'canvas', 'feed'],
  ['/doc/12', '', 'canvas', 'feed'],
  ['/source', '?kind=telegram&key=x', 'canvas', 'feed'],
  ['/study/projects/3', '', 'canvas', 'study'],
  ['/follow/saved', '', 'canvas', 'saved'],
  ['/sources', '', 'canvas', 'sources'],
  ['/discover', '', 'explore', 'discover'],
  ['/explore', '?list=x', 'explore', 'signals'],
  ['/follow/transcripts', '', 'explore', 'transcripts'],
  ['/us', '', 'explore', 'transcripts'],
  ['/follow/universe', '', 'explore', 'sectors'],
  ['/discover/industry', '', 'explore', 'sectors'],
  ['/follow/trade', '', 'explore', 'trade'],
  ['/follow/credit', '', 'explore', 'credit'],
  ['/person', '?name=x', 'explore', 'people'],
  ['/actions', '', 'explore', 'actions'],
  ['/portfolio', '', 'portfolio', 'overview'],
  ['/portfolio/holdings', '?stock=000001', 'portfolio', 'holdings'],
  ['/portfolio/principles', '', 'portfolio', 'principles'],
  ['/portfolio/events', '', 'portfolio', 'events'],
  ['/follow/stocks', '?group=2', 'portfolio', 'groups'],
  ['/follow', '', 'portfolio', 'groups'],
  ['/narrative', '?topic=AI', 'world', 'now'],
  ['/narrative/history', '', 'world', 'now'],
  ['/knowledge', '', 'world', 'graph'],
  ['/knowledge/ontology', '', 'world', 'graph'],
  ['/question/4', '', 'world', 'judgment'],
  ['/thesis', '', 'world', 'judgment'],
  ['/report', '', 'world', 'judgment'],
  ['/proxy-boards', '?board=1', 'world', 'judgment'],
]

test('every route lands on the L1/L2 in the shell contract', () => {
  for (const [path, search, section, tab] of CASES) {
    assert.deepEqual(locate(path, search), { section, tab }, `${path}${search}`)
  }
})

test('dossiers, chat and admin are destinations without an L1', () => {
  for (const p of ['/analyze/005930/summary', '/us/NVDA', '/company', '/chat', '/admin', '/archive']) {
    assert.equal(locate(p), null, p)
  }
})

test('five sections in order, each landing on its first tab', () => {
  assert.deepEqual(SECTIONS.map(s => s.label), ['홈', '탐색', '포트폴리오', '캔버스', '월드모델'])
  for (const s of SECTIONS) assert.equal(s.path, s.tabs[0].path)
})
