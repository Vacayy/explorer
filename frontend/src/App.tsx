import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react"
import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation, Outlet } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { createQueryClient } from "@/api/query"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar"
import { TopBar } from "@/components/layout/TopBar"
import { MyListPanel } from "@/components/layout/MyListPanel"
import { DesktopOnly } from "@/components/layout/DesktopOnly"
import { ChatPanel } from "@/components/chat/ChatPanel"
import { PREF, readPref, writePref } from "@/lib/shellPrefs"
import { onAskAi } from "@/lib/aiPanel"
import { SubNav } from "@/components/layout/SubNav"
import { FEED_TABS, SECTIONS, analyzeTabOf, analyzeTabs, feedSourceTab, isDocumentFeed, locate } from "@/components/layout/navConfig"
import Omnibar from "@/components/shared/Omnibar"
import AnswerWatcher from "@/components/layout/AnswerWatcher"
import { useCompany } from "@/hooks/useCompanySearch"
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts"

// Home
import { DetailNavigationMemory } from "@/components/shared/DetailNavigation"
import { DiscoveryNavigationMemory } from "@/components/shared/DiscoveryNavigationMemory"
import { DiscoveryContextTrail } from "@/components/company/DiscoveryContextTrail"
import { DiscoveryTechnicalContext } from "@/components/company/DiscoveryTechnicalContext"
import { PageHeader, PageLayout } from "@/components/shared/PageLayout"
import HomePage, { HomeBriefingPage, HomeMacroPage, HomeRiskPage } from "@/components/home/HomePage"
import ProxyBoardsPage from "@/components/proxy/ProxyBoardsPage"
import PortfolioPage from "@/components/portfolio/PortfolioPage"
import FollowPage, { SourcesPage } from "@/components/follow/FollowPage"
import TranscriptPage from "@/components/follow/TranscriptPage"
import TradePage from "@/components/follow/TradePage"
import CreditPage from "@/components/follow/CreditPage"
import RetailHeatPage from "@/components/retail/RetailHeatPage"
import SavedPage from "@/components/follow/SavedPage"

// Explore (탐색 — 신호)
import ExplorePage from "@/components/explore/ExplorePage"
import ChatPage from "@/components/chat/ChatPage"
import ActionsPage from "@/components/actions/ActionsPage"
import ProjectsPage from "@/components/study/ProjectsPage"
import ProjectPage from "@/components/study/ProjectPage"
import StocksPage from "@/components/follow/StocksPage"
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
import SectorsPage from "@/components/sectors/SectorsPage"
import NarrativePage from "@/components/explore/NarrativePage"
import NarrativeHistory from "@/components/explore/NarrativeHistory"
import WorldviewPage from "@/components/explore/WorldviewPage"
import ReportsPage from "@/components/explore/ReportsPage"
import ArchivePage from "@/components/archive/ArchivePage"
import AdminPage from "@/components/admin/AdminPage"
import MemoryReadingPage from "@/components/expectations/MemoryReadingPage"
import ExpectationsPage from "@/components/expectations/ExpectationsPage"

// Analysis
import ComparePage from "@/components/analyze/ComparePage"
import MarketAnalysisPage from "@/components/analysis/MarketAnalysisPage"
import SummaryPage from "@/components/summary/SummaryPage"
import CompanyFinancials from "@/components/company/CompanyFinancials"
import { CompanyEvidence } from "@/components/company/CompanyEvidence"
import BusinessPage from "@/components/business/BusinessPage"
import DisclosurePage from "@/components/disclosures/DisclosurePage"
import ValuationPage from "@/components/valuation/ValuationPage"
import LensPage from "@/components/lens/LensPage"
import UsDossierPage from "@/components/us/UsDossierPage"
import UsIndexPage from "@/components/us/UsIndexPage"

// Feed
import UnifiedFeedPage from "@/components/feed/UnifiedFeedPage"

// Research

const queryClient = createQueryClient()

/** 인페이지 L2 — 상단 L1과 같은 navConfig를 읽는다 (docs/specs/app-shell.md §2). 도시에는 도시에 탭, 문서 검색은 소스 탭 */
function subNavFor(pathname: string, search: string, stockCode: string | null, companyName?: string | null) {
  if (stockCode) return { tabs: analyzeTabs(stockCode, search), activeKey: analyzeTabOf(pathname), context: companyName ?? stockCode }
  if (pathname.startsWith("/narrative") && new URLSearchParams(search).has("topic")) return null
  if (pathname.startsWith("/feed") && isDocumentFeed(search)) return { tabs: FEED_TABS, activeKey: feedSourceTab(search) }
  const here = locate(pathname, search)
  const section = here && SECTIONS.find(s => s.key === here.section)
  if (!section || section.tabs.length < 2) return null
  return { tabs: section.tabs, activeKey: here.tab }
}

/** 폭 ≥1440이면 패널 기본 펼침. 사용자가 고른 값이 있으면 그 값 */
function initialOpen(key: string): boolean {
  const saved = readPref(key)
  if (saved != null) return saved === "1"
  return typeof window !== "undefined" && window.matchMedia("(min-width: 1440px)").matches
}

function Layout() {
  const { pathname, search } = useLocation()
  const [leftOpen, setLeftOpen] = useState(() => initialOpen(PREF.left))
  const [aiOpen, setAiOpen] = useState(() => initialOpen(PREF.ai))
  const aiInput = useRef<HTMLTextAreaElement | null>(null)
  const setLeft = (v: boolean) => { setLeftOpen(v); writePref(PREF.left, v ? "1" : "0") }
  const toggleAi = useCallback(() => setAiOpen(v => {
    writePref(PREF.ai, v ? "0" : "1")
    if (!v) requestAnimationFrame(() => aiInput.current?.focus())
    return !v
  }), [])
  useKeyboardShortcuts(toggleAi)
  // 'AI에게 묻기' — 어느 화면에서 보내든 패널을 연다. 인용은 패널이 받는다 (lib/aiPanel)
  useEffect(() => onAskAi(() => { setAiOpen(true); writePref(PREF.ai, "1") }), [])

  // /analyze/:stockCode/... 의 종목코드 (/analyze/compare 같은 특수 경로 제외)
  const rawCode = pathname.match(/^\/analyze\/([^/]+)/)?.[1] ?? null
  const stockCode = rawCode === "compare" ? null : rawCode
  const { data: company } = useCompany(stockCode)
  const subNav = subNavFor(pathname, search, stockCode, company?.corp_name)
  const showAi = aiOpen && !pathname.startsWith("/chat")

  return (
    <DesktopOnly>
      <TooltipProvider delayDuration={300}>
      <div className="min-h-screen bg-background">
        <Omnibar />
        <DetailNavigationMemory />
        <DiscoveryNavigationMemory />
        <SidebarProvider open={leftOpen} onOpenChange={setLeft} className="flex-col"
          style={{ "--sidebar-width": "15.5rem" } as CSSProperties}>
          <TopBar aiOpen={showAi} onToggleAi={toggleAi} />
          <div className="flex min-h-0 w-full flex-1">
            <MyListPanel currentStockCode={stockCode} />
            <SidebarInset className="min-w-0 bg-background">
              {/* --shell-offset: 풀하이트 화면이 뺄 높이 = 상단 바 + 위아래 여백 + (L2가 있으면) L2 (app-shell.md §8) */}
              <div
                className="mx-auto w-full max-w-[var(--layout-shell)] min-w-0 px-[var(--page-inset)] pt-[var(--page-inset)] pb-[var(--dock-reserve)]"
                style={{ "--shell-offset": subNav
                  ? "calc(var(--topbar-height) + var(--page-inset) + var(--dock-reserve) + var(--subnav-height))"
                  : "calc(var(--topbar-height) + var(--page-inset) + var(--dock-reserve))" } as CSSProperties}
              >
                {subNav && <SubNav tabs={subNav.tabs} activeKey={subNav.activeKey} context={subNav.context} />}
                {stockCode && !pathname.endsWith('/summary') && <DiscoveryContextTrail stockCode={stockCode} />}
                <Outlet />
              </div>
            </SidebarInset>
            {showAi && <ChatPanel companyName={company?.corp_name} onClose={toggleAi} inputRef={aiInput} />}
          </div>
        </SidebarProvider>
        <AnswerWatcher />
        <Toaster position="top-right" />
      </div>
      </TooltipProvider>
    </DesktopOnly>
  )
}

function AnalyzePage({ tab }: { tab: string }) {
  const { stockCode } = useParams<{ stockCode: string }>()
  const { search } = useLocation()
  const { data: company, isLoading } = useCompany(stockCode ?? null)
  const sourceRun = new URLSearchParams(search).get('source_run')

  if (!stockCode) return null
  if (isLoading) return <div className="text-center py-20 text-muted-foreground">로딩 중...</div>
  if (!company) return sourceRun
    ? <PageLayout header={<PageHeader title={stockCode} description="기업 기초정보 미확인 · 저장된 발견 근거" />}><DiscoveryTechnicalContext runId={sourceRun} code={stockCode} original currentUnavailable="기업 기초정보를 찾지 못해 현재 기업 분석을 열 수 없습니다. 발견 당시 저장된 차트와 판정은 아래에서 확인할 수 있습니다." /></PageLayout>
    : <div className="text-center py-20 text-muted-foreground">기업 정보를 찾을 수 없습니다.</div>

  const corpCode = company.corp_code

  switch (tab) {
    case "summary":
      return <SummaryPage stockCode={stockCode} />
    case "financials":
      return <CompanyFinancials key={stockCode} stockCode={stockCode} corpCode={corpCode} />
    case "business":
      return <BusinessPage stockCode={stockCode} corpCode={corpCode} />
    case "disclosures":
      return <DisclosurePage stockCode={stockCode} corpCode={corpCode} />
    case "valuation":
      return <ValuationPage stockCode={stockCode} />
    case "lens":
      return <LensPage code={stockCode} market="kr" />
    case "mentions":
      return <CompanyEvidence key={stockCode} company={stockCode} />
    default:
      return <Navigate to={`/analyze/${stockCode}/summary`} replace />
  }
}

function AskRedirect() {
  // /ask → /chat (옴니바·구 링크 호환, ?q= 프리필 보존)
  const { search } = useLocation()
  return <Navigate to={`/chat${search}`} replace />
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
            <Route path="home/briefing" element={<HomeBriefingPage />} />
            <Route path="home/risk" element={<HomeRiskPage />} />
            <Route path="home/macro" element={<HomeMacroPage />} />
            <Route path="proxy-boards" element={<ProxyBoardsPage />} />
            <Route path="follow" element={<FollowPage />} />
            <Route path="sources" element={<SourcesPage />} />
            <Route path="follow/stocks" element={<StocksPage />} />
            <Route path="follow/universe" element={<Navigate to="/map?view=universe" replace />} />
            <Route path="follow/transcripts" element={<TranscriptPage />} />
            <Route path="follow/trade" element={<TradePage />} />
            <Route path="follow/credit" element={<CreditPage />} />
            <Route path="retail" element={<RetailHeatPage />} />
            <Route path="follow/saved" element={<SavedPage />} />
            <Route path="portfolio" element={<PortfolioPage />} />
            <Route path="portfolio/holdings" element={<PortfolioPage tab="holdings" />} />
            <Route path="portfolio/principles" element={<PortfolioPage tab="principles" />} />
            <Route path="portfolio/events" element={<PortfolioPage tab="events" />} />
            <Route path="stocks" element={<Navigate to="/follow" replace />} />
            <Route path="archive" element={<ArchivePage />} />
            <Route path="admin" element={<AdminPage />} />
            <Route path="experiments/expectations" element={<MemoryReadingPage />} />
            <Route path="experiments/expectations/review" element={<ExpectationsPage />} />

            {/* Explore — 신호 (spine). 옛 시그널 페이지는 대체됨 */}
            <Route path="explore" element={<ExplorePage />} />
            <Route path="map" element={<SectorsPage />} />
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
            <Route path="discover" element={<MarketAnalysisPage />} />
            <Route path="discover/industry" element={<Navigate to="/map?view=chains" replace />} />
            <Route path="discover/screener" element={<Navigate to="/discover" replace />} />
            <Route path="discover/signals" element={<Navigate to="/explore" replace />} />
            <Route path="discover/alt-data" element={<Navigate to="/discover" replace />} />

            {/* Analysis */}
            <Route path="analysis/backtests" element={<Navigate to="/discover" replace />} />
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
            <Route path="research/memos" element={<Navigate to="/follow/stocks" replace />} />
            <Route path="research/catalysts" element={<Navigate to="/portfolio/events" replace />} />

            {/* Legacy redirects */}
            <Route path="industry" element={<Navigate to="/discover/industry" replace />} />
            <Route path="onchain" element={<Navigate to="/discover" replace />} />
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
