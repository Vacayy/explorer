import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

type AppMode = "home" | "discover" | "feed" | "analyze" | "research"

const DISCOVER_TABS = [
  { key: "industry", path: "/discover/industry", label: "산업군" },
  { key: "screener", path: "/discover/screener", label: "스크리너" },
  { key: "signals", path: "/discover/signals", label: "시그널" },
  { key: "alt-data", path: "/discover/alt-data", label: "대안데이터" },
] as const

const ANALYZE_TABS = [
  { key: "summary", label: "요약" },
  { key: "financials", label: "재무정보" },
  { key: "valuation", label: "밸류에이션" },
  { key: "business", label: "사업정보" },
  { key: "disclosures", label: "공시" },
] as const

const FEED_TABS = [
  { key: "telegram", path: "/feed/telegram", label: "텔레그램" },
  { key: "blogs", path: "/feed/blogs", label: "블로그" },
] as const

const RESEARCH_TABS = [
  { key: "watchlist", path: "/research/watchlist", label: "워치리스트" },
  { key: "memos", path: "/research/memos", label: "투자메모" },
  { key: "catalysts", path: "/research/catalysts", label: "카탈리스트" },
] as const

interface Props {
  stockCode: string | null
  companyName?: string | null
}

export default function ModeNavigation({ stockCode, companyName }: Props) {
  const { pathname } = useLocation()
  const activeMode = getActiveMode(pathname)
  const activeSubTab = getActiveSubTab(pathname)

  return (
    <nav className="border-b bg-card">
      <div className="mx-auto max-w-[1440px] px-6">
        {/* Level 1: Mode pills */}
        <div className="flex items-center gap-1 pt-1.5 pb-0.5">
          <ModeButton
            to="/home"
            active={activeMode === "home"}
            label="홈"
          />
          <ModeButton
            to="/discover/industry"
            active={activeMode === "discover"}
            label="발굴"
          />
          <ModeButton
            to="/feed/telegram"
            active={activeMode === "feed"}
            label="피드"
          />
          <ModeButton
            to={stockCode ? `/analyze/${stockCode}/summary` : "#"}
            active={activeMode === "analyze" && !pathname.startsWith("/analyze/compare")}
            disabled={!stockCode}
            label={stockCode && companyName ? `분석: ${companyName}` : "분석"}
          />
          <ModeButton
            to="/analyze/compare"
            active={pathname.startsWith("/analyze/compare")}
            label="VS 비교"
          />
          <ModeButton
            to="/research/watchlist"
            active={activeMode === "research"}
            label="리서치노트"
          />
        </div>

        {/* Level 2: Sub-tabs */}
        <div className="flex -mb-px">
          {activeMode === "feed" && FEED_TABS.map((tab) => (
            <SubTab key={tab.key} to={tab.path} active={activeSubTab === tab.key} label={tab.label} />
          ))}

          {activeMode === "discover" && DISCOVER_TABS.map((tab) => (
            <SubTab key={tab.key} to={tab.path} active={activeSubTab === tab.key} label={tab.label} />
          ))}

          {activeMode === "analyze" && stockCode && ANALYZE_TABS.map((tab) => (
            <SubTab
              key={tab.key}
              to={`/analyze/${stockCode}/${tab.key}`}
              active={activeSubTab === tab.key}
              label={tab.label}
            />
          ))}

          {activeMode === "research" && RESEARCH_TABS.map((tab) => (
            <SubTab key={tab.key} to={tab.path} active={activeSubTab === tab.key} label={tab.label} />
          ))}
        </div>
      </div>
    </nav>
  )
}

function ModeButton({ to, active, disabled, label }: {
  to: string; active: boolean; disabled?: boolean; label: string
}) {
  if (disabled) {
    return (
      <span className="px-4 py-1.5 text-sm rounded-md text-muted-foreground/40 cursor-not-allowed">
        {label}
      </span>
    )
  }
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
  if (pathname.startsWith("/feed")) return "feed"
  if (pathname.startsWith("/analyze")) return "analyze"
  if (pathname.startsWith("/research")) return "research"
  return "discover"
}

function getActiveSubTab(pathname: string): string | null {
  // Feed
  if (pathname.startsWith("/feed/telegram")) return "telegram"
  if (pathname.startsWith("/feed/blogs")) return "blogs"

  // Discover
  if (pathname.startsWith("/discover/industry")) return "industry"
  if (pathname.startsWith("/discover/screener")) return "screener"
  if (pathname.startsWith("/discover/signals")) return "signals"
  if (pathname.startsWith("/discover/alt-data")) return "alt-data"

  // Analyze
  const analyzeMatch = pathname.match(/^\/analyze\/[^/]+\/(\w+)/)
  if (analyzeMatch) return analyzeMatch[1]

  // Research
  if (pathname.startsWith("/research/watchlist")) return "watchlist"
  if (pathname.startsWith("/research/memos")) return "memos"
  if (pathname.startsWith("/research/catalysts")) return "catalysts"

  return null
}
