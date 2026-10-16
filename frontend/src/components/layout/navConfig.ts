/**
 * 내비게이션 단일 소스 — 상단 L1 5탭과 인페이지 L2가 같은 정의를 읽는다 (docs/specs/app-shell.md §2).
 *
 * L1 = 홈 · 탐색 · 포트폴리오 · 캔버스 · 월드모델. P3a에서 L2는 지금 URL을 가리킨다(URL 이전은 P3b).
 * 종목 도시에(/analyze, /us/:ticker, /company)는 L1이 아니라 목적지 — L2 자리에 도시에 탭을 보인다.
 */
export type SectionKey = "home" | "explore" | "portfolio" | "canvas" | "world"

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
  { key: "home", label: "홈", path: "/home", tabs: [
    { key: "dashboard", path: "/home", label: "대시보드", match: ["/home"] },
    { key: "briefing", path: "/home/briefing", label: "시장 브리핑", match: ["/home/briefing"] },
    { key: "risk", path: "/home/risk", label: "국면·리스크", match: ["/home/risk", "/retail"] },
    { key: "macro", path: "/home/macro", label: "매크로", match: ["/home/macro"] },
  ] },
  { key: "explore", label: "탐색", path: "/discover", tabs: [
    { key: "discover", path: "/discover", label: "종목 발견", match: ["/discover"] },
    { key: "signals", path: "/explore", label: "신호", match: ["/explore"] },
    { key: "transcripts", path: "/follow/transcripts", label: "컨콜", match: ["/follow/transcripts", "/us"] },
    { key: "sectors", path: "/map", label: "산업·섹터", match: ["/map", "/follow/universe", "/discover/industry"] },
    { key: "trade", path: "/follow/trade", label: "수출입", match: ["/follow/trade"] },
    { key: "credit", path: "/follow/credit", label: "회사채", match: ["/follow/credit"] },
    { key: "people", path: "/people", label: "인물", match: ["/people", "/person"] },
    { key: "actions", path: "/actions", label: "기업활동", match: ["/actions"] },
  ] },
  { key: "portfolio", label: "포트폴리오", path: "/portfolio", tabs: [
    { key: "overview", path: "/portfolio", label: "개요", match: ["/portfolio"] },
    { key: "holdings", path: "/portfolio/holdings", label: "보유", match: ["/portfolio/holdings"] },
    { key: "principles", path: "/portfolio/principles", label: "원칙", match: ["/portfolio/principles"] },
    { key: "events", path: "/portfolio/events", label: "일정", match: ["/portfolio/events"] },
    { key: "groups", path: "/follow/stocks", label: "종목 묶음", match: ["/follow/stocks", "/follow"] },
  ] },
  { key: "canvas", label: "캔버스", path: "/home?home_view=feed", tabs: [
    { key: "feed", path: "/home?home_view=feed", label: "피드", match: ["/home?home_view=feed", "/feed", "/doc/", "/source", "/synthesis/"] },
    { key: "study", path: "/study", label: "스터디", match: ["/study"] },
    { key: "saved", path: "/follow/saved", label: "저장됨", match: ["/follow/saved"] },
    { key: "sources", path: "/sources", label: "소스", match: ["/sources"] },
  ] },
  { key: "world", label: "월드모델", path: "/narrative", tabs: [
    { key: "now", path: "/narrative", label: "지금", match: ["/narrative"] },
    { key: "graph", path: "/knowledge/ontology", label: "그래프", match: ["/knowledge"] },
    { key: "judgment", path: "/questions", label: "내 판단", match: ["/questions", "/question/", "/thesis", "/report", "/proxy-boards"] },
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

export const FEED_TABS: readonly SubTab[] = [
  { key: "all", path: "/home?home_view=feed", label: "Home 피드" },
  { key: "documents", path: "/feed?view=documents", label: "문서 검색" },
  { key: "telegram", path: "/feed?source=telegram", label: "텔레그램" },
  { key: "blog", path: "/feed?source=blog", label: "블로그" },
  { key: "youtube", path: "/feed?source=youtube", label: "유튜브" },
  { key: "news", path: "/feed?source=news", label: "뉴스" },
  { key: "article", path: "/feed?source=article", label: "아티클" },
  { key: "transcript", path: "/feed?source=transcript", label: "컨콜" },
  { key: "people", path: "/feed?source=people", label: "인물" },
  { key: "canon", path: "/feed?source=canon", label: "역사" },
  // 스크랩 = 미검증(개인 투자자 블로그) — 다른 탭과 성격이 달라 맨 뒤 (D-142)
  { key: "scrap", path: "/feed?source=scrap", label: "스크랩" },
]

/** 종목 도시에 탭 — path는 종목코드가 필요해 analyzeTabs(code)로 생성 */
const ANALYZE_TAB_DEFS = [
  { key: "summary", label: "개요" },
  { key: "financials", label: "실적·사업" },
  { key: "mentions", label: "자료" },
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

/** Existing document URLs remain valid alongside the home timeline. */
export function isDocumentFeed(search: string): boolean {
  const params = new URLSearchParams(search)
  return params.get('view') === 'documents' || ['q', 'source', 'stock', 'industry', 'topic', 'page'].some(k => params.has(k))
}

/** 피드 문서 검색의 소스 탭 key — ?source= 쿼리가 상태 소스 */
export function feedSourceTab(search: string): string {
  return new URLSearchParams(search).get("source") ?? (isDocumentFeed(search) ? "documents" : "all")
}

/** 종목 도시에 탭 key — 옛 탭(사업·밸류·공시)은 가까운 탭으로 */
export function analyzeTabOf(pathname: string): string | null {
  const m = pathname.match(/^\/analyze\/[^/]+\/(\w+)/)
  if (!m) return null
  return ["business", "valuation"].includes(m[1]) ? "financials" : m[1] === "disclosures" ? "mentions" : m[1]
}
