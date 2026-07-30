import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

type AppMode = "home" | "follow" | "worldmodel" | "feed" | "chat" | "analyze" | "research" | "archive"

// L1 = 파이프라인 흐름을 좌→우로 드러낸다: 입력(팔로우)→원천(피드)→종합(월드모델). (D-057: 탐색 해체)
// Home은 흐름의 아침 요약 + 신호 대시보드(진입), 대화는 횡단 도구 — 둘은 흐름에서 구분선으로 격리.
// 월드모델은 매일 여는 종착점이라 약한 강조. 승인 대기는 헤더 상시 배지(홈에서 격상, D-056).
// 도시에(/analyze, /source)는 네비가 아니라 목적지 — 진입은 검색·레일·옴니바·링크로.
// 신호 상세(/explore?list=)·산업군·스크리너·대안데이터·리서치·백테스트는 보관함/도시에 — 라우트 유지

// 팔로우 — 내가 따라가는 것(허브) + 담당 유니버스 + 커버리지 대상(산업맵·인물·기업활동, D-057)
const FOLLOW_TABS = [
  { key: "follow", path: "/follow", label: "팔로우" },
  { key: "universe", path: "/follow/universe", label: "유니버스" },
  { key: "transcripts", path: "/follow/transcripts", label: "컨콜" },
  { key: "us", path: "/us", label: "미국" },
  { key: "trade", path: "/follow/trade", label: "수출입" },
  { key: "saved", path: "/follow/saved", label: "저장됨" },
  { key: "map", path: "/map", label: "산업 맵" },
  { key: "people", path: "/people", label: "인물" },
  { key: "actions", path: "/actions", label: "기업활동" },
] as const

// 월드모델 — 인식론적 시간축으로 L2 구성 (D-073): 내러티브(현재·서사) · 전망(미래·확률) · 지식(과거·검증).
// 전망은 질문↔리포트 토글(미래-확률 집약), 지식은 지식↔온톨로지 토글(D-052). 신호와 성격 달라 별도 모드(D-031).
const WORLDMODEL_TABS = [
  { key: "narrative", path: "/narrative", label: "내러티브" },
  { key: "outlook", path: "/thesis", label: "전망" },        // 전망 하위 [논지 감사·질문·리포트], 랜딩=논지 감사 (D-083)
  { key: "knowledge", path: "/knowledge", label: "지식" },   // 지식 안에서 지식↔온톨로지(그래프) 토글 (D-052)
] as const

const ANALYZE_TABS = [
  { key: "summary", label: "홈" },
  { key: "financials", label: "재무정보" },
  { key: "valuation", label: "밸류에이션" },
  { key: "business", label: "사업정보" },
  { key: "disclosures", label: "공시" },
  { key: "lens", label: "렌즈" },
] as const

const FEED_TABS = [
  { key: "all", path: "/feed", label: "전체" },
  { key: "telegram", path: "/feed?source=telegram", label: "텔레그램" },
  { key: "blog", path: "/feed?source=blog", label: "블로그" },
  { key: "youtube", path: "/feed?source=youtube", label: "유튜브" },
  { key: "news", path: "/feed?source=news", label: "뉴스" },
  { key: "article", path: "/feed?source=article", label: "아티클" },
  { key: "transcript", path: "/feed?source=transcript", label: "컨콜" },
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
          <ModeButton to="/home" active={activeMode === "home"} label="Home" />
          <ModeDivider />
          <ModeButton to="/follow" active={activeMode === "follow"} label="팔로우" />
          <ModeButton to="/feed" active={activeMode === "feed"} label="피드" />
          <ModeButton to="/narrative" active={activeMode === "worldmodel"} label="월드모델" emphasis />
          <ModeDivider />
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

function ModeButton({ to, active, label, emphasis }: {
  to: string; active: boolean; label: string; emphasis?: boolean
}) {
  return (
    <Link
      to={to}
      className={cn(
        "px-4 py-1.5 text-sm rounded-md transition-colors",
        active
          ? "bg-primary text-primary-foreground font-semibold"
          : emphasis
            ? "text-foreground font-medium hover:bg-muted"
            : "text-muted-foreground hover:text-foreground hover:bg-muted"
      )}
    >
      {label}
    </Link>
  )
}

// Home과 대화를 가운데 흐름(팔로우→피드→탐색→월드모델)에서 시각적으로 격리
function ModeDivider() {
  return <span aria-hidden className="mx-1 h-4 w-px self-center bg-border" />
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
  // 팔로우 — 허브 + 유니버스 + 커버리지 대상(산업맵·인물·기업활동, D-057)
  if (pathname.startsWith("/follow") || pathname.startsWith("/stocks")
      || pathname.startsWith("/map") || pathname.startsWith("/people") || pathname.startsWith("/person")
      || pathname.startsWith("/us") || pathname.startsWith("/actions")) return "follow"
  if (pathname.startsWith("/chat") || pathname.startsWith("/ask")) return "chat"
  if (pathname.startsWith("/feed") || pathname.startsWith("/doc/") || pathname.startsWith("/source")) return "feed"
  if (pathname.startsWith("/analyze")) return "analyze"
  if (pathname.startsWith("/research")) return "research"
  if (pathname.startsWith("/archive")) return "archive"
  // 월드모델 — 내러티브·리포트·세계관·지식 (D-031)
  if (pathname.startsWith("/narrative") || pathname.startsWith("/question") || pathname.startsWith("/knowledge") || pathname.startsWith("/report") || pathname.startsWith("/thesis")) return "worldmodel"
  // /explore(신호 상세)·/discover/*·/onchain — 탐색 해체 후 pill 없는 도시에 (D-057)
  return "archive"
}

function getActiveSubTab(pathname: string): string | null {
  // Feed 서브탭은 쿼리 파라미터 기반 (컴포넌트에서 직접 계산)

  // 월드모델 — 시간축(D-073): 전망 상위탭 하위에 질문(/question*)·리포트(/report), 둘 다 '전망(outlook)' 활성.
  // 온톨로지(그래프)는 지식 탭 하위(/knowledge/ontology), 둘 다 '지식' 탭 활성 (D-052)
  if (pathname.startsWith("/narrative")) return "narrative"
  if (pathname.startsWith("/question") || pathname.startsWith("/report") || pathname.startsWith("/thesis")) return "outlook"
  if (pathname.startsWith("/knowledge")) return "knowledge"

  // 팔로우 — /follow 하위(universe·transcripts)는 follow보다 먼저 매칭 + 커버리지 대상(D-057)
  if (pathname.startsWith("/follow/universe")) return "universe"
  if (pathname.startsWith("/follow/transcripts")) return "transcripts"
  if (pathname.startsWith("/follow/trade")) return "trade"
  if (pathname.startsWith("/follow/saved")) return "saved"
  if (pathname.startsWith("/us")) return "us"
  if (pathname.startsWith("/follow")) return "follow"
  if (pathname.startsWith("/map")) return "map"
  if (pathname.startsWith("/people") || pathname.startsWith("/person")) return "people"
  if (pathname.startsWith("/actions")) return "actions"

  // Analyze
  const analyzeMatch = pathname.match(/^\/analyze\/[^/]+\/(\w+)/)
  if (analyzeMatch) return analyzeMatch[1]

  return null
}
