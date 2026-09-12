import { useState, type CSSProperties } from "react"
import { BrowserRouter, Routes, Route, Navigate, useParams, useNavigate, useLocation, Outlet } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { createQueryClient } from "@/api/query"
import { Toaster } from "@/components/ui/sonner"
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar"
import Dock from "@/components/layout/Dock"
import { SubNav } from "@/components/layout/SubNav"
import { FEED_TABS, FOLLOW_TABS, WORLDMODEL_TABS, analyzeTabs, getActiveMode, getActiveSubTab, isDocumentFeed } from "@/components/layout/navConfig"
import Omnibar from "@/components/shared/Omnibar"
import FollowRail from "@/components/layout/FollowRail"
import AnswerWatcher from "@/components/layout/AnswerWatcher"
import { useCompany } from "@/hooks/useCompanySearch"
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts"

// Home
import { getHomeMode } from "@/hooks/useHomeMode"
import { DetailNavigationMemory } from "@/components/shared/DetailNavigation"
import HomePage from "@/components/home/HomePage"
import FollowPage, { SourcesPage } from "@/components/follow/FollowPage"
import UniversePage from "@/components/follow/UniversePage"
import TranscriptPage from "@/components/follow/TranscriptPage"
import TradePage from "@/components/follow/TradePage"
import SavedPage from "@/components/follow/SavedPage"

// Explore (탐색 — 신호)
import ExplorePage from "@/components/explore/ExplorePage"
import ChatPage from "@/components/chat/ChatPage"
import ActionsPage from "@/components/actions/ActionsPage"
import ProjectsPage from "@/components/study/ProjectsPage"
import ProjectPage from "@/components/study/ProjectPage"
import StudyPage from "@/components/study/StudyPage"
import DocPage from "@/components/doc/DocPage"
import SynthesisPage from "@/components/synthesis/SynthesisPage"
import SourcePage from "@/components/source/SourcePage"
import PersonPage from "@/components/person/PersonPage"
import PeopleDirectoryPage from "@/components/person/PeopleDirectoryPage"
import CompanyPage from "@/components/company/CompanyPage"
import KnowledgePage from "@/components/knowledge/KnowledgePage"
import QuestionsPage from "@/components/knowledge/QuestionsPage"
import ThesisAuditPage from "@/components/thesis/ThesisAuditPage"
import QuestionDetail from "@/components/knowledge/QuestionDetail"
import SectorMapPage from "@/components/map/SectorMapPage"
import NarrativePage from "@/components/explore/NarrativePage"
import NarrativeHistory from "@/components/explore/NarrativeHistory"
import WorldviewPage from "@/components/explore/WorldviewPage"
import ReportsPage from "@/components/explore/ReportsPage"
import ArchivePage from "@/components/archive/ArchivePage"
import AdminPage from "@/components/admin/AdminPage"
import MemoryReadingPage from "@/components/expectations/MemoryReadingPage"
import ExpectationsPage from "@/components/expectations/ExpectationsPage"

// Discovery
import IndustryPage from "@/components/industry/IndustryPage"
import OnchainPage from "@/components/onchain/OnchainPage"
import ScreenerPage from "@/components/discovery/ScreenerPage"

// Analysis
import ComparePage from "@/components/analyze/ComparePage"
import SummaryPage from "@/components/summary/SummaryPage"
import FinancialsPage from "@/components/financials/FinancialsPage"
import BusinessPage from "@/components/business/BusinessPage"
import DisclosurePage from "@/components/disclosures/DisclosurePage"
import ValuationPage from "@/components/valuation/ValuationPage"
import LensPage from "@/components/lens/LensPage"
import UsDossierPage from "@/components/us/UsDossierPage"
import UsIndexPage from "@/components/us/UsIndexPage"

// Feed
import UnifiedFeedPage from "@/components/feed/UnifiedFeedPage"

// Research
import MemosPage from "@/components/research/MemosPage"
import CatalystsPage from "@/components/research/CatalystsPage"

const queryClient = createQueryClient()

/** 모드별 인페이지 L2 — 도크 팝오버와 같은 navConfig를 읽는다 (docs/specs/dock-navigation.md §2) */
function subNavFor(pathname: string, search: string, stockCode: string | null, companyName?: string | null) {
  if (pathname.startsWith("/narrative") && new URLSearchParams(search).has("topic")) return null
  const mode = getActiveMode(pathname)
  const activeKey = getActiveSubTab(pathname, search)
  if (mode === "follow" || mode === "us") return { tabs: FOLLOW_TABS, activeKey }
  if (mode === "feed" && pathname.startsWith("/feed") && isDocumentFeed(search)) return { tabs: FEED_TABS, activeKey }
  if (mode === "worldmodel") return { tabs: WORLDMODEL_TABS, activeKey }
  if (mode === "analyze" && stockCode) return { tabs: analyzeTabs(stockCode), activeKey, context: companyName ?? stockCode }
  return null
}

function Layout() {
  useKeyboardShortcuts()
  const { pathname, search } = useLocation()

  // Extract stockCode from /analyze/:stockCode/... paths (exclude special routes like /analyze/compare)
  const stockCodeMatch = pathname.match(/^\/analyze\/([^/]+)/)
  const rawCode = stockCodeMatch ? stockCodeMatch[1] : null
  const stockCode = rawCode === "compare" ? null : rawCode
  const { data: company } = useCompany(stockCode)
  const subNav = subNavFor(pathname, search, stockCode, company?.corp_name)

  // 넓은 데스크톱에선 팔로우 레일 펼침, 그 이하에선 접힘(토글/오버레이) — 사용자 의도
  const [railOpen, setRailOpen] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 1280px)").matches,
  )

  const [feedRailOpen, setFeedRailOpen] = useState(false)
  const [detailRailOpen, setDetailRailOpen] = useState(false)
  const detailRoute = pathname.startsWith("/study/") || pathname.startsWith("/doc/") || (pathname.startsWith("/narrative") && new URLSearchParams(search).has("topic"))
  const homeFeed = pathname === "/home" && getHomeMode(search) === "feed"

  return (
    <div className="min-h-screen bg-background">
      <Omnibar />
      <DetailNavigationMemory />
      <SidebarProvider
        open={detailRoute ? detailRailOpen : homeFeed ? feedRailOpen : railOpen}
        onOpenChange={detailRoute ? setDetailRailOpen : homeFeed ? setFeedRailOpen : setRailOpen}
        style={{ "--sidebar-width": "16rem" } as CSSProperties}
      >
        <SidebarInset className="min-w-0 bg-background">
          {/* 상단 크롬 없음(D-136) — 콘텐츠가 뷰포트 최상단에서 시작. 하단은 도크 예약(--dock-reserve).
              --shell-offset(풀하이트 페이지 차감량)은 SubNav 유무로 달라져 여기서 확정한다 */}
          <div
            className="mx-auto w-full max-w-[var(--layout-shell)] min-w-0 px-[var(--page-inset)] pt-[var(--page-inset)] pb-[var(--dock-reserve)]"
            style={{ "--shell-offset": subNav ? "calc(var(--page-inset) + var(--dock-reserve) + var(--subnav-height))" : "calc(var(--page-inset) + var(--dock-reserve))" } as CSSProperties}
          >
            {subNav && <SubNav tabs={subNav.tabs} activeKey={subNav.activeKey} context={subNav.context} />}
            <Outlet />
          </div>
        </SidebarInset>
        <Dock stockCode={stockCode} companyName={company?.corp_name} />

        {/* 팔로우 레일 — 종목·채널·블로그 통합, shadcn Sidebar (docs/specs/follow-rail.md) */}
        <FollowRail currentStockCode={stockCode} />
      </SidebarProvider>
      <AnswerWatcher />
      <Toaster position="top-right" />
    </div>
  )
}

function AnalyzePage({ tab }: { tab: string }) {
  const { stockCode } = useParams<{ stockCode: string }>()
  const { data: company, isLoading } = useCompany(stockCode ?? null)

  if (!stockCode) return null
  if (isLoading) return <div className="text-center py-20 text-muted-foreground">로딩 중...</div>
  if (!company) return <div className="text-center py-20 text-muted-foreground">기업 정보를 찾을 수 없습니다.</div>

  const corpCode = company.corp_code

  switch (tab) {
    case "summary":
      return <SummaryPage stockCode={stockCode} corpCode={corpCode} />
    case "financials":
      return <FinancialsPage stockCode={stockCode} corpCode={corpCode} />
    case "business":
      return <BusinessPage stockCode={stockCode} corpCode={corpCode} />
    case "disclosures":
      return <DisclosurePage stockCode={stockCode} corpCode={corpCode} />
    case "valuation":
      return <ValuationPage stockCode={stockCode} />
    case "lens":
      return <LensPage code={stockCode} market="kr" />
    case "mentions":
      // 언급 탭은 종목 홈 우측 컬럼으로 흡수 — 기존 링크는 홈으로
      return <Navigate to={`/analyze/${stockCode}/summary`} replace />
    default:
      return <Navigate to={`/analyze/${stockCode}/summary`} replace />
  }
}

function AskRedirect() {
  // /ask → /chat (옴니바·구 링크 호환, ?q= 프리필 보존)
  const { search } = useLocation()
  return <Navigate to={`/chat${search}`} replace />
}

function IndustryRoute() {
  const navigate = useNavigate()
  return (
    <IndustryPage
      onSelectCompany={(c) => {
        if (c.stock_code) {
          navigate(`/analyze/${c.stock_code}/summary`)
        }
      }}
    />
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            {/* Default */}
            <Route index element={<Navigate to="/home" replace />} />

            {/* Home — 내 종목 follow-up */}
            <Route path="home" element={<HomePage />} />
            <Route path="follow" element={<FollowPage />} />
            <Route path="sources" element={<SourcesPage />} />
            <Route path="follow/universe" element={<UniversePage />} />
            <Route path="follow/transcripts" element={<TranscriptPage />} />
            <Route path="follow/trade" element={<TradePage />} />
            <Route path="follow/saved" element={<SavedPage />} />
            <Route path="stocks" element={<Navigate to="/follow" replace />} />
            <Route path="archive" element={<ArchivePage />} />
            <Route path="admin" element={<AdminPage />} />
            <Route path="experiments/expectations" element={<MemoryReadingPage />} />
            <Route path="experiments/expectations/review" element={<ExpectationsPage />} />

            {/* Explore — 신호 (spine). 옛 시그널 페이지는 대체됨 */}
            <Route path="explore" element={<ExplorePage />} />
            <Route path="map" element={<SectorMapPage />} />
            <Route path="narrative" element={<NarrativePage />} />
            <Route path="narrative/history" element={<NarrativeHistory />} />
            <Route path="knowledge/ontology" element={<WorldviewPage />} />
            <Route path="narrative/worldview" element={<Navigate to="/knowledge/ontology" replace />} />
            <Route path="report" element={<ReportsPage />} />
            <Route path="people" element={<PeopleDirectoryPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="questions" element={<QuestionsPage />} />
            <Route path="question/:id" element={<QuestionDetail />} />
            <Route path="thesis" element={<ThesisAuditPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="ask" element={<AskRedirect />} />
            <Route path="actions" element={<ActionsPage />} />

            {/* Discovery */}
            <Route path="discover" element={<Navigate to="/explore" replace />} />
            <Route path="discover/industry" element={<IndustryRoute />} />
            <Route path="discover/screener" element={<ScreenerPage />} />
            <Route path="discover/signals" element={<Navigate to="/explore" replace />} />
            <Route path="discover/alt-data" element={<OnchainPage />} />

            {/* Analysis */}
            <Route path="analyze/compare" element={<ComparePage />} />
            <Route path="analyze/:stockCode" element={<Navigate to="summary" replace />} />
            <Route path="analyze/:stockCode/summary" element={<AnalyzePage tab="summary" />} />
            <Route path="analyze/:stockCode/financials" element={<AnalyzePage tab="financials" />} />
            <Route path="analyze/:stockCode/valuation" element={<AnalyzePage tab="valuation" />} />
            <Route path="analyze/:stockCode/business" element={<AnalyzePage tab="business" />} />
            <Route path="analyze/:stockCode/disclosures" element={<AnalyzePage tab="disclosures" />} />
            <Route path="analyze/:stockCode/mentions" element={<AnalyzePage tab="mentions" />} />
            <Route path="analyze/:stockCode/lens" element={<AnalyzePage tab="lens" />} />
            <Route path="us" element={<UsIndexPage />} />
            <Route path="us/:ticker" element={<UsDossierPage />} />

            {/* Feed — 통합 피드 (spine). 레거시 URL은 소스 필터로 리다이렉트 */}
            <Route path="feed" element={<UnifiedFeedPage />} />
            <Route path="study" element={<ProjectsPage />} />
            <Route path="study/projects/:id" element={<ProjectPage />} />
            <Route path="study/:id" element={<StudyPage />} />
            <Route path="doc/:docId" element={<DocPage />} />
            <Route path="synthesis/:synthesisId" element={<SynthesisPage />} />
            <Route path="source" element={<SourcePage />} />
            <Route path="person" element={<PersonPage />} />
            <Route path="company" element={<CompanyPage />} />
            <Route path="feed/telegram" element={<Navigate to="/feed?source=telegram" replace />} />
            <Route path="feed/blogs" element={<Navigate to="/feed?source=blog" replace />} />

            {/* Research */}
            <Route path="research" element={<Navigate to="/follow" replace />} />
            <Route path="research/watchlist" element={<Navigate to="/follow" replace />} />
            <Route path="research/memos" element={<MemosPage />} />
            <Route path="research/catalysts" element={<CatalystsPage />} />

            {/* Legacy redirects */}
            <Route path="industry" element={<Navigate to="/discover/industry" replace />} />
            <Route path="onchain" element={<Navigate to="/discover/alt-data" replace />} />
            <Route path="company/:stockCode/:tab" element={<LegacyRedirect />} />

            {/* Catch all */}
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

/** Redirect old /company/:stockCode/:tab URLs to /analyze/:stockCode/:tab */
function LegacyRedirect() {
  const { stockCode, tab } = useParams<{ stockCode: string; tab: string }>()
  const tabMap: Record<string, string> = {
    summary: "summary", financials: "financials", business: "business",
    disclosures: "disclosures", valuation: "valuation",
    metrics: "summary", marketcap: "valuation",
  }
  const newTab = tabMap[tab ?? "summary"] ?? "summary"
  return <Navigate to={`/analyze/${stockCode}/${newTab}`} replace />
}
