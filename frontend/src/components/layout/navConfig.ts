/**
 * 내비게이션 단일 소스 — 상단 L1 6탭·모바일 하단 탭과 인페이지 L2가 같은 정의를 읽는다 (docs/specs/app-shell.md §2).
 *
 * L1 = 홈 · 피드 · 탐색 · 산업 · 포트폴리오 · Thesis (화면 구조 개편 C안). 홈 L2는 시스템 고정 탭 다섯 개(3단계), 나머지 L2는 지금 URL을 가리킨다.
 * 종목 도시에(/analyze, /us/:ticker, /company)는 L1이 아니라 목적지 — L2 자리에 도시에 탭을 보인다.
 * 시장 전체 기업활동은 홈 › 한국 시장 #actions(D-300) — /actions는 리다이렉트(?code=X는 그 종목 도시에 개요 #actions, §10.6). 리다이렉트 전 한 번은 한국 시장으로 판정.
 */
export type SectionKey = "home" | "feed" | "explore" | "industry" | "portfolio" | "world"

export interface SubTab {
  key: string
  path: string
  label: string
}

interface TabDef extends SubTab {
  /** 이 탭으로 판정하는 경로 접두어. 'path?key=value'면 그 쿼리일 때만 */
  match: readonly string[]
}

export interface SectionDef {
  key: SectionKey
  label: string
  path: string
  tabs: readonly TabDef[]
}

export const SECTIONS: readonly SectionDef[] = [
  // 홈 L2 = 시스템 고정 탭(개편 3단계). 옛 주소 /home/b/:id·/home/briefing·/home/risk·/regimes는 리다이렉트, /retail은 한국 시장으로 판정
  { key: "home", label: "홈", path: "/home", tabs: [
    { key: "dashboard", path: "/home", label: "대시보드", match: ["/home"] },
    { key: "kr", path: "/home/kr", label: "한국 시장", match: ["/home/kr", "/retail", "/actions"] },
    { key: "us", path: "/home/us", label: "미국 시장", match: ["/home/us", "/home/briefing"] },
    { key: "macro", path: "/home/macro", label: "매크로", match: ["/home/macro", "/home/risk", "/regimes"] },
    { key: "stocks", path: "/home/stocks", label: "내 종목", match: ["/home/stocks", "/follow"] },
  ] },
  // 피드 대메뉴(개편 4a단계). 옛 주소 /home?home_view=feed·/follow/saved는 리다이렉트 — 리다이렉트 전 한 프레임도 같은 탭으로 판정
  { key: "feed", label: "피드", path: "/feed", tabs: [
    { key: "feed", path: "/feed", label: "피드", match: ["/home?home_view=feed", "/feed", "/doc/", "/source"] },
    { key: "saved", path: "/feed/saved", label: "저장됨", match: ["/feed/saved", "/follow/saved"] },
  ] },
  { key: "explore", label: "탐색", path: "/discover", tabs: [
    { key: "discover", path: "/discover", label: "종목 발견", match: ["/discover", "/explore"] },
    { key: "transcripts", path: "/follow/transcripts", label: "컨콜", match: ["/follow/transcripts", "/us"] },
    { key: "people", path: "/people", label: "인물", match: ["/people", "/person"] },
    // 신호(/explore)는 종목 발견 '오늘의 신호'로 옮겨 리다이렉트(4c). 기업활동 탭은 홈 › 한국 시장으로 옮겨 없앴다(D-300)
  ] },
  // 산업 첫 탭 = 섹터 지도(/industry) → 섹터 화면(/industry/:sector). Peer 그룹은 섹터 화면 탭으로 옮겨 옛 /discover/peers·/analyze/compare는
  // 리다이렉트 전 한 프레임도 여기로 판정(D-327)
  { key: "industry", label: "산업", path: "/industry", tabs: [
    { key: "sectors", path: "/industry", label: "섹터", match: ["/industry", "/map", "/follow/universe", "/discover/industry", "/discover/peers", "/analyze/compare"] },
    { key: "trade", path: "/follow/trade", label: "수출입", match: ["/follow/trade"] },
    { key: "taiwan", path: "/follow/taiwan", label: "대만 공급망", match: ["/follow/taiwan"] },
    { key: "valuechain", path: "/value-chain", label: "밸류체인", match: ["/value-chain"] },
    { key: "credit", path: "/follow/credit", label: "회사채", match: ["/follow/credit"] },
  ] },
  { key: "portfolio", label: "포트폴리오", path: "/portfolio", tabs: [
    { key: "overview", path: "/portfolio", label: "개요", match: ["/portfolio"] },
    { key: "holdings", path: "/portfolio/holdings", label: "보유", match: ["/portfolio/holdings"] },
    { key: "principles", path: "/portfolio/principles", label: "원칙", match: ["/portfolio/principles"] },
    { key: "events", path: "/portfolio/events", label: "일정", match: ["/portfolio/events"] },
    { key: "groups", path: "/follow/stocks", label: "종목 묶음", match: ["/follow/stocks"] },
  ] },
  // key 'world'는 그대로 두고 이름만 Thesis (C안). 소스는 관리자 › 소스(/admin/sources)
  { key: "world", label: "Thesis", path: "/narrative", tabs: [
    { key: "now", path: "/narrative", label: "지금", match: ["/narrative"] },
    { key: "graph", path: "/knowledge/ontology", label: "그래프", match: ["/knowledge"] },
    { key: "judgment", path: "/questions", label: "내 판단", match: ["/questions", "/question/", "/thesis", "/report", "/proxy-boards"] },
    { key: "study", path: "/study", label: "스터디", match: ["/study"] },
  ] },
]

/** 접두어가 경로 경계에서 맞는가 — '/follow'가 '/followers'에 걸리지 않게 */
function prefixMatch(pathname: string, prefix: string): boolean {
  if (prefix.endsWith("/")) return pathname.startsWith(prefix)
  return pathname === prefix || pathname.startsWith(prefix + "/")
}

function tabMatches(pathname: string, search: string, rule: string): number {
  const [path, query] = rule.split("?")
  if (!prefixMatch(pathname, path)) return 0
  if (query) {
    const [k, v] = query.split("=")
    if (new URLSearchParams(search).get(k) !== v) return 0
  }
  return path.length + (query ? 1000 : 0)   // 더 구체적인 규칙(쿼리 > 긴 경로)이 이긴다
}

/** 현재 위치의 (L1, L2). 도시에·대화·관리자 등은 null */
export function locate(pathname: string, search = ""): { section: SectionKey; tab: string } | null {
  if (/^\/us\/[^/]+/.test(pathname)) return null     // 미국 종목 도시에 — /us 목록만 탐색 › 컨콜
  let best: { section: SectionKey; tab: string; score: number } | null = null
  for (const s of SECTIONS) for (const t of s.tabs) for (const rule of t.match) {
    const score = tabMatches(pathname, search, rule)
    if (score && (!best || score > best.score)) best = { section: s.key, tab: t.key, score }
  }
  return best && { section: best.section, tab: best.tab }
}

/** 종목 도시에 탭 — path는 종목코드가 필요해 analyzeTabs(code)로 생성 */
const ANALYZE_TAB_DEFS = [
  { key: "summary", label: "개요" },
  { key: "financials", label: "실적·사업" },
  { key: "mentions", label: "자료" },
  { key: "lens", label: "투자 렌즈" },
] as const

/** Carry only company research context, never unrelated filters or arbitrary return URLs. */
export function companyResearchSearch(search = ''): string {
  const source = new URLSearchParams(search)
  const discovery = source.get('discovery')
  const params = new URLSearchParams()
  if (discovery) params.set('discovery', discovery)
  for (const key of discovery ? ['research', 'researchTab', 'lane'] : []) {
    const value = source.get(key)
    if (value) params.set(key, value)
  }
  const sourceRun = source.get('source_run')
  if (sourceRun) params.set('source_run', sourceRun)
  for (const key of ['scan', 'scan_within', 'scan_chart', 'scan_view', 'structure_kind', 'structure_window', 'structure_swing', 'structure_fit', ...(sourceRun ? ['scan_at', 'source_compare', 'source_sort'] : [])]) {
    const value = source.get(key)
    if (value) params.set(key, value)
  }
  return params.size ? `?${params}` : ''
}

export const analyzeTabs = (stockCode: string, search = ''): SubTab[] => {
  const context = companyResearchSearch(search)
  const hasDiscovery = new URLSearchParams(context).has('discovery')
  return ANALYZE_TAB_DEFS.map((t) => ({
    key: t.key, label: hasDiscovery && t.key === 'summary' ? '기업 조사' : t.label,
    path: `/analyze/${stockCode}/${t.key}${context}`,
  }))
}

/** 종목 도시에 탭 key — 옛 탭(사업·밸류·공시)은 가까운 탭으로 */
export function analyzeTabOf(pathname: string): string | null {
  const m = pathname.match(/^\/analyze\/[^/]+\/(\w+)/)
  if (!m) return null
  return ["business", "valuation"].includes(m[1]) ? "financials" : m[1] === "disclosures" ? "mentions" : m[1]
}
