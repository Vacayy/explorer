import { BrowserRouter, Routes, Route, Navigate, useParams, useNavigate, useLocation, Outlet } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "@/components/ui/sonner"
import Header from "@/components/layout/Header"
import ModeNavigation from "@/components/layout/ModeNavigation"
import WatchlistSidebar from "@/components/layout/WatchlistSidebar"
import { TelegramChannelsSidebar } from "@/components/feed/TelegramFeedPage"
import { BlogSourcesSidebar } from "@/components/feed/BlogFeedPage"
import { useCompany } from "@/hooks/useCompanySearch"
import { addToHistory } from "@/components/layout/SearchHistory"
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts"

// Home
import HomePage from "@/components/home/HomePage"

// Explore (탐색 — 신호)
import ExplorePage from "@/components/explore/ExplorePage"
import AskPage from "@/components/ask/AskPage"
import ActionsPage from "@/components/actions/ActionsPage"

// Discovery
import IndustryPage from "@/components/industry/IndustryPage"
import OnchainPage from "@/components/onchain/OnchainPage"
import ScreenerPage from "@/components/discovery/ScreenerPage"

// Analysis
import ComparePage from "@/components/analyze/ComparePage"
import MentionsPage from "@/components/analyze/MentionsPage"
import SummaryPage from "@/components/summary/SummaryPage"
import FinancialsPage from "@/components/financials/FinancialsPage"
import BusinessPage from "@/components/business/BusinessPage"
import DisclosurePage from "@/components/disclosures/DisclosurePage"
import ValuationPage from "@/components/valuation/ValuationPage"

// Feed
import UnifiedFeedPage from "@/components/feed/UnifiedFeedPage"

// Research
import WatchlistPage from "@/components/research/WatchlistPage"
import MemosPage from "@/components/research/MemosPage"
import CatalystsPage from "@/components/research/CatalystsPage"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

function Layout() {
  useKeyboardShortcuts()
  const { pathname, search } = useLocation()

  // Extract stockCode from /analyze/:stockCode/... paths (exclude special routes like /analyze/compare)
  const stockCodeMatch = pathname.match(/^\/analyze\/([^/]+)/)
  const rawCode = stockCodeMatch ? stockCodeMatch[1] : null
  const stockCode = rawCode === "compare" ? null : rawCode
  const { data: company } = useCompany(stockCode)

  return (
    <div className="min-h-screen bg-background">
      <Header selectedCompany={company ?? null} />
      <ModeNavigation stockCode={stockCode} companyName={company?.corp_name} />

      <div className="mx-auto max-w-[1440px] flex">
        <main className="flex-1 min-w-0 p-6">
          <Outlet />
        </main>

        {pathname.startsWith("/feed") ? (
          <aside className="w-[220px] shrink-0 bg-card border-l sticky top-[110px] h-[calc(100vh-110px)] overflow-y-auto">
            {search.includes("source=blog") ? <BlogSourcesSidebar /> : <TelegramChannelsSidebar />}
          </aside>
        ) : (
          <WatchlistSidebar currentStockCode={stockCode} />
        )}
      </div>
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
      return <MentionsPage stockCode={stockCode} />
    default:
      return <Navigate to={`/analyze/${stockCode}/summary`} replace />
  }
}

function IndustryRoute() {
  const navigate = useNavigate()
  return (
    <IndustryPage
      onSelectCompany={(c) => {
        if (c.stock_code) {
          addToHistory(c)
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

            {/* Explore — 신호 (spine). 옛 시그널 페이지는 대체됨 */}
            <Route path="explore" element={<ExplorePage />} />
            <Route path="ask" element={<AskPage />} />
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
            <Route path="feed/telegram" element={<Navigate to="/feed?source=telegram" replace />} />
            <Route path="feed/blogs" element={<Navigate to="/feed?source=blog" replace />} />

            {/* Research */}
            <Route path="research" element={<Navigate to="/research/watchlist" replace />} />
            <Route path="research/watchlist" element={<WatchlistPage />} />
            <Route path="research/memos" element={<MemosPage />} />
            <Route path="research/catalysts" element={<CatalystsPage />} />

            {/* Legacy redirects */}
            <Route path="industry" element={<Navigate to="/discover/industry" replace />} />
            <Route path="onchain" element={<Navigate to="/discover/alt-data" replace />} />
            <Route path="company/:stockCode/:tab" element={<LegacyRedirect />} />

            {/* Catch all */}
            <Route path="*" element={<Navigate to="/discover/industry" replace />} />
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
