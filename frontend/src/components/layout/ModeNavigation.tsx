import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

type AppMode = "home" | "follow" | "discover" | "worldmodel" | "feed" | "chat" | "analyze" | "research" | "archive"

// P2-2 L1 재편 (product-v3.md §3): 오늘(델타)·탐색(유입)·피드(원천)·대화(판단).
// 도시에(/analyze, /source)는 네비가 아니라 목적지 — 진입은 검색·레일·옴니바·링크로.
// 산업군·스크리너·대안데이터·리서치는 보관함(/archive) — 라우트는 유지
const DISCOVER_TABS = [
  { key: "signals", path: "/explore", label: "신호" },
  { key: "map", path: "/map", label: "산업 맵" },
  { key: "people", path: "/people", label: "인물" },
  { key: "actions", path: "/actions", label: "기업활동" },
] as const

// 팔로우 — 내가 따라가는 것(허브) + 담당 유니버스(섹터 커버리지·밸류체인, D-037)
const FOLLOW_TABS = [
  { key: "follow", path: "/follow", label: "팔로우" },
  { key: "universe", path: "/follow/universe", label: "유니버스" },
] as const

// 월드모델 — 내러티브(빠른 층)·세계관(인과 그래프)·지식(느린 층)은 "같은 인과 그래프의 두 속도"(D-023).
// 신호(델타 감지)와 성격이 달라 별도 모드로 묶음 (D-031). 지식은 탐색에서 이관.
const WORLDMODEL_TABS = [
  { key: "narrative", path: "/narrative", label: "내러티브" },
  { key: "worldview", path: "/narrative/worldview", label: "세계관" },
  { key: "knowledge", path: "/knowledge", label: "지식" },
] as const

const ANALYZE_TABS = [
  { key: "summary", label: "홈" },
  { key: "financials", label: "재무정보" },
  { key: "valuation", label: "밸류에이션" },
  { key: "business", label: "사업정보" },
  { key: "disclosures", label: "공시" },
] as const

const FEED_TABS = [
  { key: "all", path: "/feed", label: "전체" },
  { key: "telegram", path: "/feed?source=telegram", label: "텔레그램" },
  { key: "blog", path: "/feed?source=blog", label: "블로그" },
  { key: "youtube", path: "/feed?source=youtube", label: "유튜브" },
  { key: "news", path: "/feed?source=news", label: "뉴스" },
  { key: "article", path: "/feed?source=article", label: "아티클" },
  { key: "people", path: "/feed?source=people", label: "인물" },
  { key: "canon", path: "/feed?source=canon", label: "역사" },
] as const

interface Props {
  stockCode: string | null
  companyName?: string | null
}

export default function ModeNavigation({ stockCode, companyName }: Props) {
  const { pathname, search } = useLocation()
  const activeMode = getActiveMode(pathname)
  const activeSubTab = getActiveSubTab(pathname)
  // 피드 서브탭은 쿼리 파라미터(source)가 상태 소스
  const feedSource = new URLSearchParams(search).get("source") ?? "all"
  const inAnalyze = activeMode === "analyze" && !pathname.startsWith("/analyze/compare")

  return (
    <nav className="bg-card">
      <div className="mx-auto max-w-[var(--layout-shell)] px-6">
        {/* Level 1: Mode pills — 판단 루프의 단계들 */}
        <div className="flex items-center gap-1 pt-1.5 pb-0.5">
          <ModeButton to="/home" active={activeMode === "home"} label="오늘" />
          <ModeButton to="/follow" active={activeMode === "follow"} label="팔로우" />
          <ModeButton to="/explore" active={activeMode === "discover"} label="탐색" />
          <ModeButton to="/narrative" active={activeMode === "worldmodel"} label="월드모델" />
          <ModeButton to="/feed" active={activeMode === "feed"} label="피드" />
          <ModeButton to="/chat" active={activeMode === "chat"} label="대화" />

          {/* 종목 도시에 컨텍스트 pill — 분석 화면에 있을 때만 나타나는 목적지 표식 */}
          {inAnalyze && stockCode && (
            <span className="ml-2 px-3 py-1 text-sm rounded-md bg-accent text-accent-foreground font-semibold">
              {companyName ?? stockCode}
            </span>
          )}
        </div>

        {/* Level 2: Sub-tabs */}
        <div className="flex -mb-px">
          {activeMode === "feed" && FEED_TABS.map((tab) => (
            <SubTab key={tab.key} to={tab.path} active={feedSource === tab.key} label={tab.label} />
          ))}

          {activeMode === "follow" && FOLLOW_TABS.map((tab) => (
            <SubTab key={tab.key} to={tab.path} active={activeSubTab === tab.key} label={tab.label} />
          ))}

          {activeMode === "discover" && DISCOVER_TABS.map((tab) => (
            <SubTab key={tab.key} to={tab.path} active={activeSubTab === tab.key} label={tab.label} />
          ))}

          {activeMode === "worldmodel" && WORLDMODEL_TABS.map((tab) => (
            <SubTab key={tab.key} to={tab.path} active={activeSubTab === tab.key} label={tab.label} />
          ))}

          {inAnalyze && stockCode && ANALYZE_TABS.map((tab) => (
            <SubTab
              key={tab.key}
              to={`/analyze/${stockCode}/${tab.key}`}
              active={activeSubTab === tab.key}
              label={tab.label}
            />
          ))}
        </div>
      </div>
    </nav>
  )
}

function ModeButton({ to, active, label }: {
  to: string; active: boolean; label: string
}) {
  return (
    <Link
      to={to}
      className={cn(
        "px-4 py-1.5 text-sm rounded-md transition-colors",
        active
          ? "bg-primary text-primary-foreground font-semibold"
          : "text-muted-foreground hover:text-foreground hover:bg-muted"
      )}
    >
      {label}
    </Link>
  )
}

function SubTab({ to, active, label }: { to: string; active: boolean; label: string }) {
  return (
    <Link
      to={to}
      className={cn(
        "px-4 py-2 text-sm border-b-2 transition-colors",
        active
          ? "font-semibold text-primary border-primary"
          : "font-normal text-muted-foreground border-transparent hover:text-foreground"
      )}
    >
      {label}
    </Link>
  )
}

function getActiveMode(pathname: string): AppMode {
  if (pathname.startsWith("/home")) return "home"
  if (pathname.startsWith("/follow") || pathname.startsWith("/stocks")) return "follow"
  if (pathname.startsWith("/chat") || pathname.startsWith("/ask")) return "chat"
  if (pathname.startsWith("/feed") || pathname.startsWith("/doc/") || pathname.startsWith("/source")) return "feed"
  if (pathname.startsWith("/analyze")) return "analyze"
  if (pathname.startsWith("/research")) return "research"
  if (pathname.startsWith("/archive")) return "archive"
  // 월드모델 — 내러티브·세계관·지식 (D-031)
  if (pathname.startsWith("/narrative") || pathname.startsWith("/knowledge")) return "worldmodel"
  return "discover" // /explore, /discover/*, /actions 모두 탐색 모드
}

function getActiveSubTab(pathname: string): string | null {
  // Feed 서브탭은 쿼리 파라미터 기반 (컴포넌트에서 직접 계산)

  // 월드모델 — worldview는 /narrative 하위라 narrative보다 먼저 매칭
  if (pathname.startsWith("/narrative/worldview")) return "worldview"
  if (pathname.startsWith("/narrative")) return "narrative"
  if (pathname.startsWith("/knowledge")) return "knowledge"

  // 팔로우 — universe는 /follow 하위라 follow보다 먼저 매칭
  if (pathname.startsWith("/follow/universe")) return "universe"
  if (pathname.startsWith("/follow")) return "follow"

  // Discover (탐색)
  if (pathname.startsWith("/explore")) return "signals"
  if (pathname.startsWith("/map")) return "map"
  if (pathname.startsWith("/people") || pathname.startsWith("/person")) return "people"
  if (pathname.startsWith("/actions")) return "actions"
  if (pathname.startsWith("/discover/industry")) return "industry"
  if (pathname.startsWith("/discover/screener")) return "screener"
  if (pathname.startsWith("/discover/alt-data")) return "alt-data"

  // Analyze
  const analyzeMatch = pathname.match(/^\/analyze\/[^/]+\/(\w+)/)
  if (analyzeMatch) return analyzeMatch[1]

  return null
}
