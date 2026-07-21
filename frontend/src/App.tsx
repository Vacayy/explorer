import { useState, type CSSProperties } from "react"
import { BrowserRouter, Routes, Route, Navigate, useParams, useNavigate, useLocation, Outlet } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { createQueryClient } from "@/api/query"
import { Toaster } from "@/components/ui/sonner"
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar"
import Header from "@/components/layout/Header"
import Omnibar from "@/components/shared/Omnibar"
import ModeNavigation from "@/components/layout/ModeNavigation"
import FollowRail from "@/components/layout/FollowRail"
import AnswerWatcher from "@/components/layout/AnswerWatcher"
import { useCompany } from "@/hooks/useCompanySearch"
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts"

// Home
import HomePage from "@/components/home/HomePage"
import FollowPage from "@/components/follow/FollowPage"

// Explore (탐색 — 신호)
import ExplorePage from "@/components/explore/ExplorePage"
import ChatPage from "@/components/chat/ChatPage"
import ActionsPage from "@/components/actions/ActionsPage"
import DocPage from "@/components/doc/DocPage"
import SourcePage from "@/components/source/SourcePage"
import PersonPage from "@/components/person/PersonPage"
import PeopleDirectoryPage from "@/components/person/PeopleDirectoryPage"
import CompanyPage from "@/components/company/CompanyPage"
import KnowledgePage from "@/components/knowledge/KnowledgePage"
import SectorMapPage from "@/components/map/SectorMapPage"
import NarrativePage from "@/components/explore/NarrativePage"
import WorldviewPage from "@/components/explore/WorldviewPage"
import IssueDetailPage from "@/components/explore/IssueDetailPage"
import ArchivePage from "@/components/archive/ArchivePage"

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

// Feed
import UnifiedFeedPage from "@/components/feed/UnifiedFeedPage"

// Research
import MemosPage from "@/components/research/MemosPage"
import CatalystsPage from "@/components/research/CatalystsPage"

const queryClient = createQueryClient()

function Layout() {
  useKeyboardShortcuts()
  const { pathname } = useLocation()

  // Extract stockCode from /analyze/:stockCode/... paths (exclude special routes like /analyze/compare)
  const stockCodeMatch = pathname.match(/^\/analyze\/([^/]+)/)
  const rawCode = stockCodeMatch ? stockCodeMatch[1] : null
  const stockCode = rawCode === "compare" ? null : rawCode
  const { data: company } = useCompany(stockCode)

  // 넓은 데스크톱에선 팔로우 레일 펼침, 그 이하에선 접힘(토글/오버레이) — 사용자 의도
  const [railDefaultOpen] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 1280px)").matches,
  )

  return (
    <div className="min-h-screen bg-background">
      <Omnibar />
      <SidebarProvider
        defaultOpen={railDefaultOpen}
        style={{ "--sidebar-width": "16rem" } as CSSProperties}
      >
        <SidebarInset className="min-w-0 bg-background">
          <Header />
          <ModeNavigation stockCode={stockCode} companyName={company?.corp_name} />
          <div className="mx-auto w-full max-w-[var(--layout-shell)] min-w-0 p-6">
            <Outlet />
          </div>
        </SidebarInset>

        {/* 팔로우 레일 — 종목·채널·블로그 통합, shadcn Sidebar (docs/specs/follow-rail.md) */}
        <FollowRail currentStockCode={stockCode} />
      </SidebarProvider>
      <AnswerWatcher />
      <Toaster />
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
            <Route path="stocks" element={<Navigate to="/follow" replace />} />
            <Route path="archive" element={<ArchivePage />} />

            {/* Explore — 신호 (spine). 옛 시그널 페이지는 대체됨 */}
            <Route path="explore" element={<ExplorePage />} />
            <Route path="issue/:nodeId" element={<IssueDetailPage />} />
            <Route path="map" element={<SectorMapPage />} />
            <Route path="narrative" element={<NarrativePage />} />
            <Route path="narrative/worldview" element={<WorldviewPage />} />
            <Route path="people" element={<PeopleDirectoryPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
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

            {/* Feed — 통합 피드 (spine). 레거시 URL은 소스 필터로 리다이렉트 */}
            <Route path="feed" element={<UnifiedFeedPage />} />
            <Route path="doc/:docId" element={<DocPage />} />
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
