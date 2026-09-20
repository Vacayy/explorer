import type { LucideIcon } from "lucide-react"
import { Bookmark, Globe, House, MessageSquare, BookOpen, ScanSearch } from "lucide-react"

/**
 * 내비게이션 단일 소스 — 도크(L1·팝오버)와 인페이지 SubNav(L2)가 같은 정의를 읽는다 (docs/specs/dock-navigation.md §2).
 *
 * L1 = 파이프라인 흐름을 좌→우로 드러낸다: 입력(팔로우)→원천(피드)→종합(월드모델). (D-057: 탐색 해체)
 * Home은 흐름의 아침 요약 + 신호 대시보드(진입), 대화는 횡단 도구 — 둘은 흐름에서 구분선으로 격리.
 * 월드모델은 매일 여는 종착점이라 약한 강조. 도시에(/analyze, /us)는 네비가 아니라 목적지 — 도크에 '열린 도시에' 임시 항목으로만.
 */
export type AppMode = "study" | "home" | "discover" | "follow" | "feed" | "worldmodel" | "chat" | "analyze" | "us" | "archive"

export interface SubTab {
  key: string
  path: string
  label: string
}

export interface ModeDef {
  key: AppMode
  label: string
  path: string
  icon: LucideIcon
  emphasis?: boolean
  /** 앞에 구분선 — Home·대화를 가운데 흐름에서 시각적으로 격리 */
  dividerBefore?: boolean
  tabs?: readonly SubTab[]
}

// 팔로우 — 내가 따라가는 것(허브) + 담당 유니버스 + 커버리지 대상(산업맵·인물·기업활동, D-057)
export const FOLLOW_TABS: readonly SubTab[] = [
  { key: "saved", path: "/follow/saved", label: "저장됨" },
  { key: "follow", path: "/follow", label: "관심목록" },
  { key: "stocks", path: "/follow/stocks", label: "종목 묶음" },
  { key: "universe", path: "/follow/universe", label: "유니버스" },
  { key: "transcripts", path: "/follow/transcripts", label: "컨콜" },
  { key: "us", path: "/us", label: "미국" },
  { key: "trade", path: "/follow/trade", label: "수출입" },
  { key: "map", path: "/map", label: "산업 맵" },
  { key: "people", path: "/people", label: "인물" },
  { key: "actions", path: "/actions", label: "기업활동" },
]

// 월드모델 — 인식론적 시간축으로 L2 구성 (D-073): 내러티브(현재·서사) · 전망(미래·확률) · 지식(과거·검증).
export const WORLDMODEL_TABS: readonly SubTab[] = [
  { key: "narrative", path: "/narrative", label: "내러티브" },
  { key: "outlook", path: "/thesis", label: "전망" },        // 전망 하위 [논지 감사·질문·리포트], 랜딩=논지 감사 (D-083)
  { key: "knowledge", path: "/knowledge", label: "지식" },   // 지식 안에서 지식↔온톨로지(그래프) 토글 (D-052)
]

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
  if (!discovery) return ''
  const params = new URLSearchParams({ discovery })
  for (const key of ['research', 'researchTab', 'lane']) {
    const value = source.get(key)
    if (value) params.set(key, value)
  }
  return `?${params}`
}

export const analyzeTabs = (stockCode: string, search = ''): SubTab[] => {
  const context = companyResearchSearch(search)
  return ANALYZE_TAB_DEFS.map((t) => ({
    key: t.key, label: context && t.key === 'summary' ? '기업 조사' : t.label,
    path: `/analyze/${stockCode}/${t.key}${context}`,
  }))
}

export const MODES: readonly ModeDef[] = [
  { key: "home", label: "Home", path: "/home", icon: House },
  { key: "discover", label: "종목 발견", path: "/discover", icon: ScanSearch },
  { key: "follow", label: "관심목록", path: "/follow/saved", icon: Bookmark, dividerBefore: true, tabs: FOLLOW_TABS },
  { key: "worldmodel", label: "월드모델", path: "/narrative", icon: Globe, emphasis: true, tabs: WORLDMODEL_TABS },
  { key: "study", label: "스터디", path: "/study", icon: BookOpen },
  { key: "chat", label: "대화", path: "/chat", icon: MessageSquare, dividerBefore: true },
]

export function getActiveMode(pathname: string): AppMode {
  if (pathname === "/discover" || pathname.startsWith("/analysis/backtests")) return "discover"
  if (pathname.startsWith("/study")) return "study"
  if (pathname.startsWith("/home")) return "home"
  if (pathname.startsWith("/us")) return "us"
  // 팔로우 — 허브 + 유니버스 + 커버리지 대상(산업맵·인물·기업활동, D-057)
  if (pathname.startsWith("/follow") || pathname.startsWith("/stocks")
      || pathname.startsWith("/map") || pathname.startsWith("/people") || pathname.startsWith("/person")
      || pathname.startsWith("/actions")) return "follow"
  if (pathname.startsWith("/chat") || pathname.startsWith("/ask")) return "chat"
  if (pathname.startsWith("/feed") || pathname.startsWith("/doc/") || pathname.startsWith("/source")) return "feed"
  if (pathname.startsWith("/analyze")) return "analyze"
  // 월드모델 — 내러티브·리포트·세계관·지식 (D-031)
  if (pathname.startsWith("/narrative") || pathname.startsWith("/question") || pathname.startsWith("/knowledge")
      || pathname.startsWith("/report") || pathname.startsWith("/thesis")) return "worldmodel"
  // /explore(신호 상세)·/discover/*·/onchain·/archive·/admin — pill 없는 도시에 (D-057)
  return "archive"
}

/** 도크 L1 활성 — /us 도시에는 팔로우 흐름(미국 서브탭)에 속한다 */
export function dockModeOf(mode: AppMode): AppMode {
  return mode === "us" ? "follow" : mode === "feed" ? "home" : mode
}

/** Existing document URLs remain valid alongside the home timeline. */
export function isDocumentFeed(search: string): boolean {
  const params = new URLSearchParams(search)
  return params.get('view') === 'documents' || ['q', 'source', 'stock', 'industry', 'topic', 'page'].some(k => params.has(k))
}

/** 현재 경로의 L2 탭 key. 피드는 ?source= 쿼리가 상태 소스 */
export function getActiveSubTab(pathname: string, search: string): string | null {
  if (pathname.startsWith("/feed")) return new URLSearchParams(search).get("source") ?? (isDocumentFeed(search) ? "documents" : "all")

  // 월드모델 — 시간축(D-073): 전망 상위탭 하위에 질문(/question*)·리포트(/report), 둘 다 '전망(outlook)' 활성.
  // 온톨로지(그래프)는 지식 탭 하위(/knowledge/ontology), 둘 다 '지식' 탭 활성 (D-052)
  if (pathname.startsWith("/narrative")) return "narrative"
  if (pathname.startsWith("/question") || pathname.startsWith("/report") || pathname.startsWith("/thesis")) return "outlook"
  if (pathname.startsWith("/knowledge")) return "knowledge"

  // 팔로우 — /follow 하위(universe·transcripts)는 follow보다 먼저 매칭 + 커버리지 대상(D-057)
  if (pathname.startsWith("/follow/stocks")) return "stocks"
  if (pathname.startsWith("/follow/universe")) return "universe"
  if (pathname.startsWith("/follow/transcripts")) return "transcripts"
  if (pathname.startsWith("/follow/trade")) return "trade"
  if (pathname.startsWith("/follow/saved")) return "saved"
  if (pathname.startsWith("/us")) return "us"
  if (pathname.startsWith("/follow")) return "follow"
  if (pathname.startsWith("/map")) return "map"
  if (pathname.startsWith("/people") || pathname.startsWith("/person")) return "people"
  if (pathname.startsWith("/actions")) return "actions"

  const analyzeMatch = pathname.match(/^\/analyze\/[^/]+\/(\w+)/)
  if (analyzeMatch) return ["business", "valuation"].includes(analyzeMatch[1]) ? "financials" : analyzeMatch[1] === "disclosures" ? "mentions" : analyzeMatch[1]

  return null
}
