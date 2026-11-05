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
  ['/home/kr', '', 'home', 'kr'],
  ['/home/us', '', 'home', 'us'],
  ['/home/macro', '', 'home', 'macro'],
  ['/home/stocks', '', 'home', 'stocks'],
  // 옛 홈 주소 — 리다이렉트 전 한 프레임도 같은 탭으로 판정
  ['/home/b/3', '', 'home', 'dashboard'],
  ['/home/briefing', '', 'home', 'us'],
  ['/home/risk', '', 'home', 'macro'],
  ['/regimes', '', 'home', 'macro'],
  ['/retail', '', 'home', 'kr'],
  // 피드
  ['/home', '?home_view=feed', 'feed', 'feed'],
  ['/feed', '', 'feed', 'feed'],
  ['/feed', '?view=documents', 'feed', 'feed'],
  ['/feed/telegram', '', 'feed', 'feed'],
  ['/feed/blogs', '', 'feed', 'feed'],
  ['/doc/12', '', 'feed', 'feed'],
  ['/source', '?kind=telegram&key=x', 'feed', 'feed'],
  ['/feed', '?channel_type=news', 'feed', 'feed'],
  ['/feed/saved', '', 'feed', 'saved'],
  ['/feed/saved', '?kind=doc', 'feed', 'saved'],
  ['/follow/saved', '', 'feed', 'saved'],
  // 탐색 (기업활동은 이행 중 탭)
  ['/discover', '', 'explore', 'discover'],
  ['/discover/screener', '', 'explore', 'discover'],
  ['/discover/signals', '', 'explore', 'discover'],
  ['/discover/alt-data', '', 'explore', 'discover'],
  ['/discover/peers', '', 'explore', 'peers'],
  ['/follow/transcripts', '', 'explore', 'transcripts'],
  // 4d — 컨콜: 시즌 개요 · 섹터 상세 · 콜 상세 · 기업 목록(옛 /us는 리다이렉트)
  ['/follow/transcripts', '?view=season', 'explore', 'transcripts'],
  ['/follow/transcripts', '?view=season&season=2026Q2', 'explore', 'transcripts'],
  ['/follow/transcripts', '?view=season&sector=dcinfra', 'explore', 'transcripts'],
  ['/follow/transcripts', '?view=season&pick=VRT', 'explore', 'transcripts'],
  ['/follow/transcripts', '?t=447', 'explore', 'transcripts'],
  ['/follow/transcripts', '?view=proxies', 'explore', 'transcripts'],
  ['/us', '', 'explore', 'transcripts'],
  ['/people', '', 'explore', 'people'],
  ['/person', '?name=x', 'explore', 'people'],
  // 4c — 옛 신호 탭(/explore)은 종목 발견 '오늘의 신호'로, VS 비교(/analyze/compare)는 Peer 그룹으로 리다이렉트
  ['/explore', '', 'explore', 'discover'],
  ['/explore', '?list=high_52w', 'explore', 'discover'],
  ['/discover', '?signal=high_52w', 'explore', 'discover'],
  ['/discover', '?panel=history', 'explore', 'discover'],
  ['/discover/peers', '?view=research&group=package_substrate&stock=007810', 'explore', 'peers'],
  ['/analyze/compare', '?stocks=005930,000660', 'explore', 'peers'],
  ['/actions', '', 'explore', 'actions'],
  // 산업
  ['/map', '', 'industry', 'sectors'],
  ['/map', '?view=universe', 'industry', 'sectors'],
  ['/follow/universe', '', 'industry', 'sectors'],
  ['/discover/industry', '', 'industry', 'sectors'],
  ['/map', '?view=map', 'industry', 'sectors'],
  ['/map', '?group=금융&sort=long', 'industry', 'sectors'],
  ['/follow/trade', '', 'industry', 'trade'],
  ['/follow/trade', '?hs=854232&trade_sort=surge', 'industry', 'trade'],
  ['/follow/taiwan', '', 'industry', 'taiwan'],
  ['/follow/taiwan', '?tw_layer=foundry&tw=2330', 'industry', 'taiwan'],
  ['/value-chain', '?node=x', 'industry', 'valuechain'],
  ['/follow/credit', '', 'industry', 'credit'],
  ['/follow/credit', '?credit=ORCL,CRWV&credit_range=3m', 'industry', 'credit'],
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
  ['/admin/sources', '', null, null],
  ['/archive', '', null, null],
  ['/chat', '', null, null],
  ['/ask', '', null, null],
  ['/stocks', '', null, null],
  ['/company', '', null, null],
  ['/company/005930/summary', '', null, null],
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
  assert.deepEqual(tabs.home, ['대시보드', '한국 시장', '미국 시장', '매크로', '내 종목'])
  assert.deepEqual(tabs.feed, ['피드', '저장됨'])
  assert.deepEqual(tabs.explore, ['종목 발견', 'Peer 그룹', '컨콜', '인물', '기업활동'])
  assert.deepEqual(tabs.industry, ['산업·섹터', '수출입', '대만 공급망', '밸류체인', '회사채'])
  assert.deepEqual(tabs.world, ['지금', '그래프', '내 판단', '스터디'])
})

test('tab paths resolve back to their own tab', () => {
  for (const s of SECTIONS) for (const t of s.tabs) {
    const [p, q] = t.path.split('?')
    assert.deepEqual(locate(p, q ? `?${q}` : ''), { section: s.key, tab: t.key }, t.path)
  }
})

// ia-redesign §10.6 — 옛 홈 주소는 고정 탭으로 보낸다(쿼리 유지). 화면 컴포넌트가 아니라 리다이렉트여야 한다
const REDIRECTS = [
  ['home/b/:boardId', '/home'],
  ['home/briefing', '/home/us'],
  ['home/risk', '/home/macro'],
  ['regimes', '/home/macro#history'],
  // 4a단계 — 저장됨은 피드 하위, 소스는 관리자 하위
  ['follow/saved', '/feed/saved'],
  ['sources', '/admin/sources'],
  // 4c단계 — VS 비교는 Peer 성과 비교로(?stocks=는 Peer 화면이 그룹·종목으로 푼다)
  ['analyze/compare', '/discover/peers'],
  // 4d단계 — 미국 기업 목록은 컨콜 기업 목록으로(종목 도시에 /us/:ticker는 그대로)
  ['us', '/follow/transcripts'],
]

test('old home URLs redirect to the fixed home tabs', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  for (const [route, to] of REDIRECTS) {
    const m = app.match(new RegExp(`<Route path="${route}" element=\\{<KeepQueryRedirect to="([^"]+)" />\\} />`))
    assert.ok(m, `${route} must be a KeepQueryRedirect`)
    assert.equal(m[1], to, route)
  }
})

test('home has no user menus: no board routes, dialogs or grid layout left', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.ok(!app.includes('NewBoardDialog'))
  assert.ok(!app.includes('useHomeBoards'))
  const home = readFileSync(new URL('../src/components/home/HomePage.tsx', import.meta.url), 'utf8')
  assert.ok(!home.includes('react-grid-layout') && !home.includes('home/Dashboard'))
})

test('old feed URL (/home?home_view=feed) is sent to /feed with the rest of its query', () => {
  const home = readFileSync(new URL('../src/components/home/HomePage.tsx', import.meta.url), 'utf8')
  assert.match(home, /getHomeMode\(search\) === 'feed'/)
  assert.match(home, /rest\.delete\('home_view'\)/)
  assert.match(home, /<Navigate to=\{`\/feed/)
  const feed = SECTIONS.find(s => s.key === 'feed')
  assert.deepEqual(feed.tabs.map(t => t.path), ['/feed', '/feed/saved'])
})

test('old signals tab (/explore) lands on 종목 발견 #signals and maps ?list= to the signal sheet', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(app, /<Route path="explore" element=\{<ExploreRedirect \/>\} \/>/)
  assert.match(app, /params\.set\("signal", list\)/)
  assert.match(app, /#signals`\} replace/)
  assert.match(app, /<Route path="discover\/signals" element=\{<Navigate to="\/discover#signals" replace \/>\} \/>/)
  assert.ok(!app.includes('ExplorePage') && !app.includes('ComparePage'))
  // 기업활동은 도시에 단계까지 그대로(/actions·/actions?code=)
  assert.match(app, /<Route path="actions" element=\{<ActionsPage \/>\} \/>/)
})
