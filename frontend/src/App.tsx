import { ActiveQueryStatus } from "@/components/shared/ActiveQueryStatus"
import { toast } from "sonner"
import { ErrorBoundary } from "@/components/shared/ErrorBoundary"
import { QueryState } from "@/components/shared/QueryState"
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation, Outlet } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { createQueryClient } from "@/api/query"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { TopBar } from "@/components/layout/TopBar"
import { TabBar } from "@/components/layout/TabBar"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { useMediaQuery, MOBILE_QUERY, PANEL_INLINE_QUERY } from "@/hooks/useMediaQuery"
import { ChatPanel } from "@/components/chat/ChatPanel"
import { PREF, readPref, writePref } from "@/lib/shellPrefs"
import { onAskAi, onOpenAi } from "@/lib/aiPanel"
import { SubNav } from "@/components/layout/SubNav"
import { SECTIONS, analyzeTabOf, analyzeTabs, locate } from "@/components/layout/navConfig"
import Omnibar from "@/components/shared/Omnibar"
import AnswerWatcher from "@/components/layout/AnswerWatcher"
import { useCompany } from "@/hooks/useCompanySearch"
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts"
import { US_TABS, usTabOf, usTabPath } from "@/lib/dossier"

// Home
import { DetailNavigationMemory } from "@/components/shared/DetailNavigation"
import { DiscoveryNavigationMemory } from "@/components/shared/DiscoveryNavigationMemory"
import { DiscoveryContextTrail } from "@/components/company/DiscoveryContextTrail"
import { DiscoveryTechnicalContext } from "@/components/company/DiscoveryTechnicalContext"
import { PageHeader, PageLayout } from "@/components/shared/PageLayout"
import HomePage, { HomeKrPage, HomeUsPage } from "@/components/home/HomePage"
import HomeStocksPage from "@/components/home/HomeStocksPage"
import HomeMacroPage from "@/components/home/HomeMacroPage"
import { withSearch } from "@/lib/macroPage"
import { proxiesUrl } from "@/lib/judgment"
import PortfolioPage from "@/components/portfolio/PortfolioPage"
import FollowPage from "@/components/follow/FollowPage"
import TranscriptPage from "@/components/follow/TranscriptPage"
import TradePage from "@/components/follow/TradePage"
import ValueChainPage from "@/components/explore/ValueChainPage"
import CreditPage from "@/components/follow/CreditPage"
import TaiwanPage from "@/components/industry/TaiwanPage"
import RetailHeatPage from "@/components/retail/RetailHeatPage"
import SavedPage from "@/components/follow/SavedPage"

// Explore (탐색)
import ChatPage from "@/components/chat/ChatPage"
import ProjectsPage from "@/components/study/ProjectsPage"
import ProjectPage from "@/components/study/ProjectPage"
import StocksPage from "@/components/follow/StocksPage"
import StudyPage from "@/components/study/StudyPage"
import DocPage from "@/components/doc/DocPage"
import SourcePage from "@/components/source/SourcePage"
import PersonPage from "@/components/person/PersonPage"
import PeopleDirectoryPage from "@/components/person/PeopleDirectoryPage"
import CompanyPage from "@/components/company/CompanyPage"
import QuestionsPage from "@/components/knowledge/QuestionsPage"
import ThesisAuditPage from "@/components/thesis/ThesisAuditPage"
import QuestionDetail from "@/components/knowledge/QuestionDetail"
import SectorsPage from "@/components/sectors/SectorsPage"
import NarrativePage from "@/components/explore/NarrativePage"
import NarrativeHistory from "@/components/explore/NarrativeHistory"
import WorldviewPage from "@/components/explore/WorldviewPage"
import ReportsPage from "@/components/explore/ReportsPage"
import ArchivePage from "@/components/archive/ArchivePage"
import { UsageTracker } from "@/components/shared/UsageTracker"
import AdminPage from "@/components/admin/AdminPage"

// Analysis
import PeerCatalogPage from "@/components/peers/PeerCatalogPage"
import MarketAnalysisPage from "@/components/analysis/MarketAnalysisPage"
import SummaryPage from "@/components/summary/SummaryPage"
import CompanyFinancials from "@/components/company/CompanyFinancials"
import { CompanyMentions } from "@/components/company/CompanyMentions"
import { KrDossierHead } from "@/components/company/KrDossierHead"
import { PageContainer } from "@/components/shared/PageContainer"
import BusinessPage from "@/components/business/BusinessPage"
import DisclosurePage from "@/components/disclosures/DisclosurePage"
import ValuationPage from "@/components/valuation/ValuationPage"
import LensPage from "@/components/lens/LensPage"
import UsDossierPage from "@/components/us/UsDossierPage"

// Feed
import FeedPage from "@/components/feed/FeedPage"

// Research

const queryClient = createQueryClient((error, { background }) => {
  toast.error(error.message, { id: `api-${error.message}`, description: background ? '최신 데이터 갱신에 실패했습니다.' : undefined })
})

/** 인페이지 L2 — 상단 L1과 같은 navConfig를 읽는다 (docs/specs/app-shell.md §2). 도시에는 도시에 탭 */
function subNavFor(pathname: string, search: string, stockCode: string | null, companyName?: string | null) {
  if (stockCode) return { tabs: analyzeTabs(stockCode, search), activeKey: analyzeTabOf(pathname), context: companyName ?? stockCode }
  const ticker = pathname.match(/^\/us\/([^/]+)\/?$/)?.[1]
  if (ticker) return { tabs: US_TABS.map(t => ({ key: t.key, label: t.label, path: usTabPath(ticker, t.key) })), activeKey: usTabOf(search), context: ticker.toUpperCase() }
  const here = locate(pathname, search)
  const section = here && SECTIONS.find(s => s.key === here.section)
  if (!section || section.tabs.length < 2) return null
  return { tabs: section.tabs, activeKey: here.tab }
}

/** 폭 ≥1440이면 패널 기본 펼침. 사용자가 고른 값이 있으면 그 값. 폭 <1024에서는 오버레이라 늘 닫힌 채 시작 */
function initialOpen(key: string): boolean {
  if (typeof window !== "undefined" && !window.matchMedia(PANEL_INLINE_QUERY).matches) return false
  const saved = readPref(key)
  if (saved != null) return saved === "1"
  return typeof window !== "undefined" && window.matchMedia("(min-width: 1440px)").matches
}

function Layout() {
  const { pathname, search } = useLocation()
  const [aiOpen, setAiOpen] = useState(() => initialOpen(PREF.ai))
  const aiInput = useRef<HTMLTextAreaElement | null>(null)
  const panelInline = useMediaQuery(PANEL_INLINE_QUERY)
  const phone = useMediaQuery(MOBILE_QUERY)
  const toggleAi = useCallback(() => setAiOpen(v => {
    if (window.matchMedia(PANEL_INLINE_QUERY).matches) writePref(PREF.ai, v ? "0" : "1")
    if (!v) requestAnimationFrame(() => aiInput.current?.focus())
    return !v
  }), [])
  useKeyboardShortcuts(toggleAi)
  // 'AI에게 묻기' — 어느 화면에서 보내든 패널을 연다. 인용은 패널이 받는다 (lib/aiPanel)
  useEffect(() => onAskAi(() => { setAiOpen(true); if (window.matchMedia(PANEL_INLINE_QUERY).matches) writePref(PREF.ai, "1") }), [])
  // 화면의 '이 자료로 대화' 같은 버튼 — 질문 없이 패널만 연다(보는 화면은 패널이 자동 첨부)
  useEffect(() => onOpenAi(() => { setAiOpen(true); requestAnimationFrame(() => aiInput.current?.focus()) }), [])

  // /analyze/:stockCode/... 의 종목코드 (/analyze/compare 같은 특수 경로 제외)
  const rawCode = pathname.match(/^\/analyze\/([^/]+)/)?.[1] ?? null
  const stockCode = rawCode === "compare" ? null : rawCode
  const { data: company } = useCompany(stockCode)
  const subNav = subNavFor(pathname, search, stockCode, company?.corp_name)
  const showAi = aiOpen && !pathname.startsWith("/chat")
  // 오버레이 대화는 다른 화면으로 가면 닫는다(근거 링크를 누르면 그 화면이 보이게)
  useEffect(() => { if (!window.matchMedia(PANEL_INLINE_QUERY).matches) setAiOpen(false) }, [pathname])

  return (
      <TooltipProvider delayDuration={300}>
      <div className="min-h-screen bg-background">
        <Omnibar />
        <DetailNavigationMemory />
        <DiscoveryNavigationMemory />
        <UsageTracker />
        <div className="flex min-h-svh w-full flex-col">
          <TopBar aiOpen={showAi} onToggleAi={toggleAi} />
          <div className="flex min-h-0 w-full flex-1">
            <main className="relative flex w-full min-w-0 flex-1 flex-col bg-background">
              {/* --shell-offset: 풀하이트 화면이 뺄 높이 = 상단 바 + 위아래 여백 + (L2가 있으면) L2 (app-shell.md §8) */}
              <div
                className="mx-auto w-full max-w-[var(--layout-shell)] min-w-0 px-[var(--page-inset)] pt-[var(--page-inset)] pb-[var(--dock-reserve)]"
                style={{ "--shell-offset": subNav
                  ? "calc(var(--topbar-height) + var(--page-inset) + var(--dock-reserve) + var(--subnav-height))"
                  : "calc(var(--topbar-height) + var(--page-inset) + var(--dock-reserve))" } as CSSProperties}
              >
                {subNav && <SubNav tabs={subNav.tabs} activeKey={subNav.activeKey} context={subNav.context} />}
                <ActiveQueryStatus />
                {stockCode && !pathname.endsWith('/summary') && <DiscoveryContextTrail stockCode={stockCode} />}
                <ErrorBoundary key={pathname + search} onReset={() => { void queryClient.refetchQueries({ type: "active", predicate: query => query.state.status === "error" }) }}><Outlet /></ErrorBoundary>
              </div>
            </main>
            {showAi && panelInline && <ChatPanel companyName={company?.corp_name} onClose={toggleAi} inputRef={aiInput} />}
          </div>
          <TabBar />
        </div>
        {/* 폭 <1024: AI 대화는 오른쪽 오버레이, 폰(<768)은 아래에서 올라오는 시트(ia-redesign §4.32) */}
        {!panelInline && (
          <Sheet open={showAi} onOpenChange={v => { if (v !== showAi) toggleAi() }}>
            <SheetContent side={phone ? "bottom" : "right"} showCloseButton={false}
              className={phone ? "gap-0 rounded-t-xl p-0 data-[side=bottom]:h-[88dvh]" : "w-full gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-md"}>
              <SheetTitle className="sr-only">AI 대화</SheetTitle>
              <SheetDescription className="sr-only">지금 보는 화면을 맥락으로 함께 보냅니다.</SheetDescription>
              <ChatPanel companyName={company?.corp_name} onClose={toggleAi} inputRef={aiInput} overlay />
            </SheetContent>
          </Sheet>
        )}
        <AnswerWatcher />
        <Toaster position="top-right" />
      </div>
      </TooltipProvider>
  )
}

function AnalyzePage({ tab }: { tab: string }) {
  const { stockCode } = useParams<{ stockCode: string }>()
  const { search } = useLocation()
  const companyQuery = useCompany(stockCode ?? null)
  const { data: company } = companyQuery
  const sourceRun = new URLSearchParams(search).get('source_run')

  if (!stockCode) return null
  if (company === undefined) return <QueryState query={companyQuery}>{() => null}</QueryState>
  if (!company) return sourceRun
    ? <PageLayout header={<PageHeader title={stockCode} description="기업 기초정보 미확인 · 저장된 발견 근거" />}><DiscoveryTechnicalContext runId={sourceRun} code={stockCode} original currentUnavailable="기업 기초정보를 찾지 못해 현재 기업 분석을 열 수 없습니다. 발견 당시 저장된 차트와 판정은 아래에서 확인할 수 있습니다." /></PageLayout>
    : <div className="text-center py-20 text-muted-foreground">기업 정보를 찾을 수 없습니다.</div>

  const corpCode = company.corp_code

  // 개요·실적·사업·자료·투자 렌즈는 같은 도시에 머리를 쓴다(ia-redesign §4.9·§4.13). 핵심 지표 띠는 개요에서만
  const withHead = (body: ReactNode) => <div className="space-y-3"><KrDossierHead stockCode={stockCode} metrics={tab === "summary"} />{body}</div>
  switch (tab) {
    case "summary":
      return withHead(<SummaryPage stockCode={stockCode} />)
    case "financials":
      return withHead(<CompanyFinancials key={stockCode} stockCode={stockCode} corpCode={corpCode} />)
    case "business":
      return <BusinessPage stockCode={stockCode} corpCode={corpCode} />
    case "disclosures":
      return <DisclosurePage stockCode={stockCode} corpCode={corpCode} />
    case "valuation":
      return <ValuationPage stockCode={stockCode} />
    case "lens":
      return withHead(<LensPage code={stockCode} market="kr" />)
    case "mentions":
      return withHead(<PageContainer><CompanyMentions key={stockCode} company={stockCode} market="kr" /></PageContainer>)
    default:
      return <Navigate to={`/analyze/${stockCode}/summary`} replace />
  }
}

/** 옮긴 화면으로 보낸다 — 쿼리는 그대로 넘긴다(ia-redesign §10.6) */
function KeepQueryRedirect({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={withSearch(to, search)} replace />
}

/** /actions — 시장 전체 목록은 홈 › 한국 시장 #actions(D-300), ?code=X는 그 종목 도시에 개요 맨 아래 #actions(§10.6). 쿼리는 그대로 */
function ActionsRoute() {
  const { search } = useLocation()
  const code = new URLSearchParams(search).get("code")?.trim()
  if (code && /^[0-9A-Z]{6}$/i.test(code)) return <Navigate to={withSearch(`/analyze/${code.toUpperCase()}/summary#actions`, search)} replace />
  return <Navigate to={withSearch("/home/kr#actions", search)} replace />
}

/** /explore?list=<type> → /discover?signal=<type>#signals (다른 쿼리는 그대로) */
function ExploreRedirect() {
  const { search } = useLocation()
  const params = new URLSearchParams(search)
  const list = params.get("list")
  if (list) { params.delete("list"); params.set("signal", list) }
  const query = params.toString()
  return <Navigate to={`/discover${query ? `?${query}` : ""}#signals`} replace />
}

/** 옛 프록시 보드(/proxy-boards?board=) → Thesis › 내 판단 '지표 보드'(/questions?view=proxies, ia-redesign §10.6). 쿼리는 그대로 */
function ProxyBoardsRedirect() {
  const { search } = useLocation()
  return <Navigate to={proxiesUrl(search)} replace />
}

function AskRedirect() {
  // /ask → /chat (옴니바·구 링크 호환, ?q= 프리필 보존)
  const { search } = useLocation()
  return <Navigate to={`/chat${search}`} replace />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary onReset={() => { void queryClient.refetchQueries({ type: "active", predicate: query => query.state.status === "error" }) }}><BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            {/* Default */}
            <Route index element={<Navigate to="/home" replace />} />

            {/* Home — 시스템 고정 탭 다섯 개 (home-widgets.md §0). 옛 홈 주소는 리다이렉트(ia-redesign §10.6) */}
            <Route path="home" element={<HomePage />} />
            <Route path="home/kr" element={<HomeKrPage />} />
            <Route path="home/us" element={<HomeUsPage />} />
            <Route path="home/macro" element={<HomeMacroPage />} />
            <Route path="home/stocks" element={<HomeStocksPage />} />
            <Route path="home/b/:boardId" element={<KeepQueryRedirect to="/home" />} />
            <Route path="home/briefing" element={<KeepQueryRedirect to="/home/us" />} />
            <Route path="home/risk" element={<KeepQueryRedirect to="/home/macro" />} />
            <Route path="regimes" element={<KeepQueryRedirect to="/home/macro#history" />} />
            <Route path="proxy-boards" element={<ProxyBoardsRedirect />} />
            <Route path="follow" element={<FollowPage />} />
            <Route path="sources" element={<KeepQueryRedirect to="/admin/sources" />} />
            <Route path="follow/stocks" element={<StocksPage />} />
            <Route path="follow/universe" element={<Navigate to="/map?view=universe" replace />} />
            <Route path="follow/transcripts" element={<TranscriptPage />} />
            <Route path="follow/trade" element={<TradePage />} />
            <Route path="follow/taiwan" element={<TaiwanPage />} />
            <Route path="value-chain" element={<ValueChainPage />} />
            <Route path="follow/credit" element={<CreditPage />} />
            <Route path="retail" element={<RetailHeatPage />} />
            <Route path="follow/saved" element={<KeepQueryRedirect to="/feed/saved" />} />
            <Route path="portfolio" element={<PortfolioPage />} />
            <Route path="portfolio/holdings" element={<PortfolioPage tab="holdings" />} />
            <Route path="portfolio/principles" element={<PortfolioPage tab="principles" />} />
            <Route path="portfolio/events" element={<PortfolioPage tab="events" />} />
            <Route path="stocks" element={<Navigate to="/follow" replace />} />
            <Route path="archive" element={<ArchivePage />} />
            <Route path="admin" element={<AdminPage />} />
            <Route path="admin/sources" element={<AdminPage />} />
            <Route path="experiments/expectations" element={<Navigate to="/chat" replace />} />
            <Route path="experiments/expectations/review" element={<Navigate to="/chat" replace />} />

            {/* 옛 탐색 › 신호 → 종목 발견 '오늘의 신호'(ia-redesign §10.6). ?list=<type>은 신호 목록 시트(?signal=)로 */}
            <Route path="explore" element={<ExploreRedirect />} />
            <Route path="map" element={<SectorsPage />} />
            <Route path="narrative" element={<NarrativePage />} />
            <Route path="narrative/history" element={<NarrativeHistory />} />
            <Route path="knowledge/ontology" element={<WorldviewPage />} />
            <Route path="narrative/worldview" element={<Navigate to="/knowledge/ontology" replace />} />
            <Route path="report" element={<ReportsPage />} />
            <Route path="people" element={<PeopleDirectoryPage />} />
            {/* 지식 목록 제거 — 그래프(온톨로지)는 그대로(ia-redesign §10.6·#17). 세계관 브리핑은 Thesis › 지금 전제 칸으로 */}
            <Route path="knowledge" element={<KeepQueryRedirect to="/knowledge/ontology" />} />
            <Route path="questions" element={<QuestionsPage />} />
            <Route path="question/:id" element={<QuestionDetail />} />
            <Route path="thesis" element={<ThesisAuditPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="ask" element={<AskRedirect />} />
            <Route path="actions" element={<ActionsRoute />} />

            {/* Discovery */}
            <Route path="discover" element={<MarketAnalysisPage />} />
            <Route path="discover/peers" element={<PeerCatalogPage />} />
            <Route path="discover/industry" element={<Navigate to="/map?view=chains" replace />} />
            <Route path="discover/screener" element={<Navigate to="/discover" replace />} />
            <Route path="discover/signals" element={<Navigate to="/discover#signals" replace />} />
            <Route path="discover/alt-data" element={<Navigate to="/discover" replace />} />

            {/* Analysis */}
            <Route path="analysis/backtests" element={<Navigate to="/discover" replace />} />
            {/* VS 비교 → Peer 성과 비교(ia-redesign §10.6). ?stocks=는 Peer 화면이 그룹·종목으로 풀어 쓴다 */}
            <Route path="analyze/compare" element={<KeepQueryRedirect to="/discover/peers" />} />
            <Route path="analyze/:stockCode" element={<Navigate to="summary" replace />} />
            <Route path="analyze/:stockCode/summary" element={<AnalyzePage tab="summary" />} />
            <Route path="analyze/:stockCode/financials" element={<AnalyzePage tab="financials" />} />
            <Route path="analyze/:stockCode/valuation" element={<AnalyzePage tab="valuation" />} />
            <Route path="analyze/:stockCode/business" element={<AnalyzePage tab="business" />} />
            <Route path="analyze/:stockCode/disclosures" element={<AnalyzePage tab="disclosures" />} />
            <Route path="analyze/:stockCode/mentions" element={<AnalyzePage tab="mentions" />} />
            <Route path="analyze/:stockCode/lens" element={<AnalyzePage tab="lens" />} />
            <Route path="us" element={<KeepQueryRedirect to="/follow/transcripts" />} />
            <Route path="us/:ticker" element={<UsDossierPage />} />

            {/* Feed — 통합 피드 (spine). 레거시 URL은 소스 필터로 리다이렉트 */}
            <Route path="feed" element={<FeedPage />} />
            <Route path="feed/saved" element={<SavedPage />} />
            <Route path="study" element={<ProjectsPage />} />
            <Route path="study/projects/:id" element={<ProjectPage />} />
            <Route path="study/:id" element={<StudyPage />} />
            <Route path="doc/:docId" element={<DocPage />} />
            <Route path="synthesis/:synthesisId" element={<Navigate to="/study" replace />} />
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
      </BrowserRouter></ErrorBoundary>
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
