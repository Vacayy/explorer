import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { locate, SECTIONS } from '../src/components/layout/navConfig.ts'

// docs/specs/app-shell.md §2 판정 표 — App.tsx의 모든 라우트(파라미터는 예시 값)와 대표 쿼리.
// null = L1 밖(도시에·대화·관리자·리다이렉트 전용 경로)
const CASES = [
  // 홈
  ['/home', '', 'home', 'dashboard'],
  ['/home', '?home_view=market', 'home', 'dashboard'],
  ['/home/b/3', '', 'home', 'dashboard'],
  ['/home/briefing', '', 'home', 'briefing'],
  ['/home/risk', '', 'home', 'risk'],
  ['/retail', '', 'home', 'risk'],
  ['/home/macro', '', 'home', 'macro'],
  // 피드
  ['/home', '?home_view=feed', 'feed', 'feed'],
  ['/feed', '', 'feed', 'feed'],
  ['/feed', '?view=documents', 'feed', 'feed'],
  ['/feed/telegram', '', 'feed', 'feed'],
  ['/feed/blogs', '', 'feed', 'feed'],
  ['/doc/12', '', 'feed', 'feed'],
  ['/source', '?kind=telegram&key=x', 'feed', 'feed'],
  ['/follow/saved', '', 'feed', 'saved'],
  // 탐색 (신호·기업활동은 이행 중 탭)
  ['/discover', '', 'explore', 'discover'],
  ['/discover/screener', '', 'explore', 'discover'],
  ['/discover/signals', '', 'explore', 'discover'],
  ['/discover/alt-data', '', 'explore', 'discover'],
  ['/discover/peers', '', 'explore', 'peers'],
  ['/follow/transcripts', '', 'explore', 'transcripts'],
  ['/us', '', 'explore', 'transcripts'],
  ['/people', '', 'explore', 'people'],
  ['/person', '?name=x', 'explore', 'people'],
  ['/explore', '?list=x', 'explore', 'signals'],
  ['/actions', '', 'explore', 'actions'],
  // 산업 (국면 이력은 이행 중 탭)
  ['/map', '', 'industry', 'sectors'],
  ['/map', '?view=universe', 'industry', 'sectors'],
  ['/follow/universe', '', 'industry', 'sectors'],
  ['/discover/industry', '', 'industry', 'sectors'],
  ['/follow/trade', '', 'industry', 'trade'],
  ['/value-chain', '?node=x', 'industry', 'valuechain'],
  ['/follow/credit', '', 'industry', 'credit'],
  ['/regimes', '', 'industry', 'regimes'],
  // 포트폴리오
  ['/portfolio', '', 'portfolio', 'overview'],
  ['/portfolio/holdings', '?stock=000001', 'portfolio', 'holdings'],
  ['/portfolio/principles', '', 'portfolio', 'principles'],
  ['/portfolio/events', '', 'portfolio', 'events'],
  ['/follow/stocks', '?group=2', 'portfolio', 'groups'],
  ['/follow', '', 'portfolio', 'groups'],
  // Thesis
  ['/narrative', '?topic=AI', 'world', 'now'],
  ['/narrative/history', '', 'world', 'now'],
  ['/narrative/worldview', '', 'world', 'now'],
  ['/knowledge', '', 'world', 'graph'],
  ['/knowledge/ontology', '', 'world', 'graph'],
  ['/questions', '', 'world', 'judgment'],
  ['/question/4', '', 'world', 'judgment'],
  ['/thesis', '', 'world', 'judgment'],
  ['/report', '', 'world', 'judgment'],
  ['/proxy-boards', '?board=1', 'world', 'judgment'],
  ['/study', '', 'world', 'study'],
  ['/study/projects/4', '', 'world', 'study'],
  ['/study/4', '', 'world', 'study'],
  // L1 밖
  ['/sources', '', null, null],
  ['/admin', '', null, null],
  ['/archive', '', null, null],
  ['/chat', '', null, null],
  ['/ask', '', null, null],
  ['/stocks', '', null, null],
  ['/company', '', null, null],
  ['/company/005930/summary', '', null, null],
  ['/analyze/compare', '', null, null],
  ['/analyze/005930', '', null, null],
  ['/analyze/005930/summary', '', null, null],
  ['/analyze/005930/financials', '', null, null],
  ['/analyze/005930/valuation', '', null, null],
  ['/analyze/005930/business', '', null, null],
  ['/analyze/005930/disclosures', '', null, null],
  ['/analyze/005930/mentions', '', null, null],
  ['/analyze/005930/lens', '', null, null],
  ['/us/NVDA', '', null, null],
  ['/synthesis/1', '', null, null],
  ['/analysis/backtests', '', null, null],
  ['/experiments/expectations', '', null, null],
  ['/experiments/expectations/review', '', null, null],
  ['/research', '', null, null],
  ['/research/watchlist', '', null, null],
  ['/research/memos', '', null, null],
  ['/research/catalysts', '', null, null],
  ['/industry', '', null, null],
  ['/onchain', '', null, null],
]

test('every route lands on the L1/L2 in the shell contract', () => {
  for (const [path, search, section, tab] of CASES) {
    assert.deepEqual(locate(path, search), section ? { section, tab } : null, `${path}${search}`)
  }
})

test('the table covers every route declared in App.tsx', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const declared = [...app.matchAll(/<Route path="([^"]+)"/g)].map(m => m[1]).filter(p => p !== '*')
  const covered = new Set(CASES.map(([p]) => p.replace(/^\//, '')))
  const examples = { ':boardId': '3', ':stockCode': '005930', ':tab': 'summary', ':ticker': 'NVDA', ':id': '4', ':docId': '12', ':synthesisId': '1' }
  for (const route of declared) {
    const concrete = route.replace(/:\w+/g, k => examples[k])
    assert.ok(covered.has(concrete), `App.tsx route '${route}' has no case in the nav table`)
  }
})

test('six sections in C-plan order, each landing on its first tab', () => {
  assert.deepEqual(SECTIONS.map(s => s.label), ['홈', '피드', '탐색', '산업', '포트폴리오', 'Thesis'])
  for (const s of SECTIONS) assert.equal(s.path, s.tabs[0].path)
})

test('L2 tabs follow the plan, transitional tabs last', () => {
  const tabs = Object.fromEntries(SECTIONS.map(s => [s.key, s.tabs.map(t => t.label)]))
  assert.deepEqual(tabs.feed, ['피드', '저장됨'])
  assert.deepEqual(tabs.explore, ['종목 발견', 'Peer 그룹', '컨콜', '인물', '신호', '기업활동'])
  assert.deepEqual(tabs.industry, ['산업·섹터', '수출입', '밸류체인', '회사채', '국면 이력'])
  assert.deepEqual(tabs.world, ['지금', '그래프', '내 판단', '스터디'])
})

test('tab paths resolve back to their own tab', () => {
  for (const s of SECTIONS) for (const t of s.tabs) {
    const [p, q] = t.path.split('?')
    assert.deepEqual(locate(p, q ? `?${q}` : ''), { section: s.key, tab: t.key }, t.path)
  }
})
